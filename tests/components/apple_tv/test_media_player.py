"""Tests for Apple TV media player."""

from unittest.mock import AsyncMock, MagicMock, patch

from pyatv.const import DeviceModel, FeatureName, FeatureState, Protocol
from pyatv.exceptions import InvalidStateError
import pytest

from homeassistant.components.apple_tv.media_player import AppleTvMediaPlayer
from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_PLAY_MEDIA,
    MediaType,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant

from .common import create_conf, mrp_service

from tests.common import MockConfigEntry

APPLE_TV_DOMAIN = "apple_tv"
_MEDIA_URL = "http://example.com/audio.mp3"
_ENTITY_ID = "media_player.living_room_homepod"


@pytest.fixture
def mock_atv() -> AsyncMock:
    """Create a mock Apple TV interface."""
    atv = AsyncMock()
    atv.close = MagicMock()
    atv.features = MagicMock()
    atv.push_updater = MagicMock()
    atv.stream = AsyncMock()
    atv.power = MagicMock()
    atv.audio = MagicMock()
    atv.metadata = AsyncMock()
    atv.device_info.model = DeviceModel.HomePodMini
    atv.device_info.raw_model = "AudioAccessory5,1"
    atv.device_info.version = "17.0"
    atv.device_info.mac = "AA:BB:CC:DD:EE:FF"

    # Report StreamFile as available, PlayUrl as unsupported
    feature_info_available = MagicMock()
    feature_info_available.state = FeatureState.Available
    feature_info_unavailable = MagicMock()
    feature_info_unavailable.state = FeatureState.Unsupported

    atv.features.all_features.return_value = {
        FeatureName.StreamFile: feature_info_available,
        FeatureName.PlayUrl: feature_info_unavailable,
    }
    atv.features.in_state.return_value = False

    return atv


@pytest.fixture
async def mock_config_entry(
    hass: HomeAssistant,
    mock_async_zeroconf: MagicMock,
    mock_atv: AsyncMock,
) -> MockConfigEntry:
    """Set up Apple TV integration with mocked pyatv."""
    entry = MockConfigEntry(
        domain=APPLE_TV_DOMAIN,
        title="Living Room HomePod",
        unique_id="mrpid",
        data={
            CONF_ADDRESS: "127.0.0.1",
            CONF_NAME: "Living Room HomePod",
            "credentials": {str(Protocol.MRP.value): "mrp_creds"},
            "identifiers": ["mrpid"],
        },
    )
    entry.add_to_hass(hass)

    scan_result = create_conf("127.0.0.1", "Living Room HomePod", mrp_service())

    with (
        patch("homeassistant.components.apple_tv.scan", return_value=[scan_result]),
        patch("homeassistant.components.apple_tv.connect", return_value=mock_atv),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_play_media_stream_file(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_atv: AsyncMock,
) -> None:
    """Test play_media calls stream_file when StreamFile feature is available."""
    with (
        patch.object(AppleTvMediaPlayer, "_is_feature_available", return_value=True),
        patch(
            "homeassistant.components.apple_tv.media_player.is_streamable",
            return_value=True,
        ),
    ):
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                "entity_id": _ENTITY_ID,
                ATTR_MEDIA_CONTENT_TYPE: MediaType.MUSIC,
                ATTR_MEDIA_CONTENT_ID: _MEDIA_URL,
            },
            blocking=True,
        )

    mock_atv.stream.stream_file.assert_called_once_with(_MEDIA_URL)


async def test_play_media_already_streaming_logs_warning(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_atv: AsyncMock,
) -> None:
    """Test that InvalidStateError when already streaming is handled gracefully."""
    mock_atv.stream.stream_file.side_effect = InvalidStateError(
        "already streaming to device"
    )

    with (
        patch.object(AppleTvMediaPlayer, "_is_feature_available", return_value=True),
        patch(
            "homeassistant.components.apple_tv.media_player.is_streamable",
            return_value=True,
        ),
        patch(
            "homeassistant.components.apple_tv.media_player._LOGGER"
        ) as mock_logger,
    ):
        # Should not raise; the exception must be caught and logged as a warning
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                "entity_id": _ENTITY_ID,
                ATTR_MEDIA_CONTENT_TYPE: MediaType.MUSIC,
                ATTR_MEDIA_CONTENT_ID: _MEDIA_URL,
            },
            blocking=True,
        )

    mock_atv.stream.stream_file.assert_called_once()
    mock_logger.warning.assert_called_once()
    assert "already streaming" in mock_logger.warning.call_args[0][0]
