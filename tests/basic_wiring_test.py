import asyncio
import logging
import pytest
from unittest import mock
from unittest.mock import create_autospec

import lyngdorf
from lyngdorf.api import LyngdorfApi, LyngdorfProtocol
from lyngdorf.mp60 import LyngdorfMP60Client

_LOGGER = logging.getLogger(__package__)

SETUP_LAST_RESPONSE="AUDTYPE"
SETUP_RESPONSES = [
    "!DEVICE(MP-60)",
    "!POWER(1)",
    "!POWERZONE2(0)",
    "!AUDIN(1)",
    '!AUDMODE(1)"Dolby Upmixer"',
    "!RPFOCCOUNT(2)",
    '!RPFOC(9)"Global"',
    '!RPFOC(1)"Focus 1"',
    '!RPFOC(1)"Focus 1"',
    "!AUDMODECOUNT(10)",
    '!AUDMODE(0)"None"',
    '!AUDMODE(1)"Dolby Upmixer"',
    '!AUDMODE(2)"Neural:X"',
    '!AUDMODE(3)"Auro-3D"',
    '!AUDMODE(4)"Auro-2D"',
    '!AUDMODE(5)"Auro-Stereo"',
    '!AUDMODE(6)"Auro-Native"',
    '!AUDMODE(7)"Legacy"',
    '!AUDMODE(8)"Stereo"',
    '!AUDMODE(9)"Party"',
    '!SRC(0)"Apple TV"',
    "!SRCCOUNT(24)",
    '!SRC(0)"Apple TV"',
    '!SRC(1)"Playstation"',
    '!SRC(2)"HDMI 3"',
    '!SRC(3)"HDMI 4"',
    '!SRC(4)"HDMI 5"',
    '!SRC(5)"TV"',
    '!SRC(6)"SPDIF 1 (Optical)"',
    '!SRC(7)"SPDIF 2 (Optical)"',
    '!SRC(8)"SPDIF 3 (Optical)"',
    '!SRC(9)"SPDIF 4 (Optical)"',
    '!SRC(10)"SPDIF 5 (AES/EBU)"',
    '!SRC(11)"SPDIF 6 (Coaxial)"',
    '!SRC(12)"SPDIF 7 (Coaxial)"',
    '!SRC(13)"SPDIF 8 (Coaxial)"',
    '!SRC(14)"USB Audio"',
    '!SRC(15)"Network Player"',
    '!SRC(16)"airable"',
    '!SRC(17)"vTuner"',
    '!SRC(18)"TIDAL"',
    '!SRC(19)"Spotify"',
    '!SRC(20)"AirPlay"',
    '!SRC(21)"Roon"',
    '!SRC(22)"DLNA"',
    '!SRC(23)"Storage"',
    "!VOL(-281)",
    "!ZVOL(-550)",
    "!VIDIN(1)",
    "!VIDTYPE(2160p50 RGB 4:4:4)",
    "!MUTEOFF",
    "!ZMUTEON",
    "!STREAMTYPE(2)",
    "!ZSTREAMTYPE(3)",
    "!AUDTYPE(PCM zero, 2.0.0)",
]


FAKE_IP = "0.0.0.0"


class TestMainFunctions:
    future = None

    def test_logging(self):
        _LOGGER.debug("Hello from debug logging")

    def test_instantiate(self):
        LyngdorfMP60Client(FAKE_IP)

    @pytest.mark.asyncio
    async def test_powers(self):
        # Receive a volume level from the processor, and validate our API has determined the volume correctly
        def test_function(client: LyngdorfMP60Client):
            assert client.power_on
            assert not client.zone_b_power_on

        await self._test_receiving_commands(SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function)

        # check that when we set the volume the receiver gets the correct command

        def client_functions(client: LyngdorfMP60Client):
            client.power_on=True
            client.power_on=False
            client.zone_b_power_on=True
            client.zone_b_power_on=False
            
        def assertion_function(client: LyngdorfMP60Client, commandsSent: []):
            assert ['!POWERONMAIN', '!POWEROFFMAIN', '!POWERONZONE2', '!POWEROFFZONE2'] == commandsSent
            _LOGGER.fatal(','.join(commandsSent))

        await self._test_sending_commands(['!AUDTYPE(PCM zero, 2.0.0)'], "AUDTYPE", client_functions, assertion_function)
        
    @pytest.mark.asyncio
    async def test_volumes_and_mutes(self):
        # Receive a volume level from the processor, and validate our API has determined the volume correctly
        def test_function(client: LyngdorfMP60Client):
            assert client.volume == -28.1
            assert client._zone_b_volume == -55.0
            assert client.mute_enabled == False
            assert client.zone_b_mute_enabled == True

        await self._test_receiving_commands(SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function)

        # check that when we set the volume the receiver gets the correct command

        def client_functions(client: LyngdorfMP60Client):
            client.volume = -22
            client.volume_up()
            client.volume_down()
            client.zone_b_volume_up()
            client.zone_b_volume_down()
            client.mute_enabled=True
            client.mute_enabled=False
            client.zone_b_mute_enabled=True
            client.zone_b_mute_enabled=False
            
        def assertion_function(client: LyngdorfMP60Client, commandsSent: []):
            assert ['!VOL(-220)', '!VOL+', '!VOL-', '!ZVOL+', '!ZVOL-', '!MUTEON', '!MUTEOFF', '!ZMUTEON', '!ZMUTEOFF'] == commandsSent
            _LOGGER.fatal(','.join(commandsSent))

        await self._test_sending_commands(['!AUDTYPE(PCM zero, 2.0.0)'], "AUDTYPE", client_functions, assertion_function)

    @pytest.mark.asyncio
    async def test_audio_sources(self):
        # # Check that the sources are set by the mock processor and the current source is playstation as we will shortly change it
        def test_function(client: LyngdorfMP60Client):
            assert len(client.available_sources) == 24
            assert "Playstation" in client.available_sources
            assert client.audio_source == "Apple TV"

        await self._test_receiving_commands(SETUP_RESPONSES, "AUDTYPE", test_function)

        # Now we set the audio source and make sure that the correct command is sent to the processor
        def test_function(client: LyngdorfMP60Client, commandsSent: []):
            assert "!SRC(1)" in commandsSent

        def client_functions(client: LyngdorfMP60Client):
            client.audio_source = "Playstation"

        await self._test_sending_commands(
            SETUP_RESPONSES, "AUDTYPE", client_functions, test_function
        )

    async def _test_receiving_commands(
        self, commands_received, wait_for_command, test_function
    ):
        transport = mock.Mock()
        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            # pylint: disable=protected-access
            protocol._on_connection_lost = proto._on_connection_lost
            # pylint: disable=protected-access
            protocol._on_message = proto._on_message
            return [transport, proto]

        client = LyngdorfMP60Client(FAKE_IP)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            try:
                test_function(client)
            except Exception as err:
                _LOGGER.fatal("puke", err)
            await client.async_disconnect()

    def _callback(self, param1, param2):
        self.future.set_result(True)

    async def _test_sending_commands(
        self, commands_received, wait_for_command, client_functions, test_function
    ):
        transport = mock.Mock()

        protocol = LyngdorfProtocol(None, None)

        def create_conn(proto_lambda, host, port):
            proto = proto_lambda()
            # pylint: disable=protected-access
            protocol._on_connection_lost = proto._on_connection_lost
            # pylint: disable=protected-access
            protocol._on_message = proto._on_message
            # pylint: disable=protected-access
            return [transport, proto]

        client = LyngdorfMP60Client(FAKE_IP)

        # # pylint: disable=protected-access
        # write_function=create_autospec(client._api._protocol.write, return_value=None)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            with mock.patch(
                "lyngdorf.api.LyngdorfProtocol.write", new_callable=mock.Mock
            ) as write_mock:
                debug_mock.return_value.create_connection = AsyncMock(
                    side_effect=create_conn
                )
                await client.async_connect()
                self.future = asyncio.Future()
                client._api.register_callback(wait_for_command, self._callback)
                protocol.data_received(
                    bytes("\r".join(commands_received) + "\r", "utf-8")
                )
                await self.future

                before_length = len(write_mock.call_args_list)

                client_functions(client)

                after_list = list(
                    map(
                        lambda call: call.args[0].replace("\r", ""),
                        write_mock.call_args_list[before_length:],
                    )
                )
                _LOGGER.debug("functions sent to processor [%s]", ", ".join(after_list))
                test_function(client, after_list)

                await client.async_disconnect()

    def _callback(self, param1, param2):
        self.future.set_result(True)


class AsyncMock(mock.MagicMock):
    """Mocking async methods compatible to python 3.7."""

    # pylint: disable=invalid-overridden-method,useless-super-delegation
    async def __call__(self, *args, **kwargs):
        """Call."""
        return super().__call__(*args, **kwargs)
