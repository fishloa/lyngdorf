import asyncio
import logging
import pytest
from unittest import mock
from unittest.mock import create_autospec

from lyngdorf.const import LyngdorfModel, Msg
from lyngdorf.api import LyngdorfProtocol
from lyngdorf.device import Receiver, async_create_receiver

_LOGGER = logging.getLogger(__package__)

SETUP_LAST_RESPONSE = "AUDTYPE"
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
    "!RPVOICOUNT(2)",
    '!RPVOI(0)"Voice 0"',
    '!RPVOI(1)"Voice 1"',
    '!RPVOI(1)"Voice 1"',
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
    '!ZSRC(0)"Apple TV"',
    "!ZSRCCOUNT(2)",
    '!ZSRC(0)"Apple TV"',
    '!ZSRC(1)"Wonk"',
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
    "!VIDIN(2)",
    "!VIDTYPE(2160p50 RGB 4:4:4)",
    "!MUTEOFF",
    "!ZMUTEON",
    "!STREAMTYPE(2)",
    "!ZSTREAMTYPE(3)",
    "!AUDTYPE(PCM zero, 2.0.0)",
]


FAKE_IP = "0.0.0.0"
CALL_COUNT = 0


class TestMainFunctions:
    future = None
    
    def test_model(self):
        mp60: LyngdorfModel=LyngdorfModel.MP_60
        l= f'{mp60.lookup_command(Msg.PONG)}'
        assert l=="PONG"   

    def test_logging(self):
        _LOGGER.debug("Hello from debug logging")

    @pytest.mark.asyncio
    async def test_instantiate(self):
        client0 = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        assert client0.model.model=="mp-60"
        assert client0.model.manufacturer=="Lyngdorf"
        assert client0.model.name=="MP_60"
        

    @pytest.mark.asyncio
    async def test_powers(self):
        # Receive a volume level from the processor, and validate our API has determined the volume correctly
        def test_function(client: Receiver):
            assert client.power_on
            assert not client.zone_b_power_on

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function, None
        )

        # check that when we set the volume the receiver gets the correct command

        def client_functions(client: Receiver):
            client.power_on = True
            client.power_on = False
            client.zone_b_power_on = True
            client.zone_b_power_on = False

        def assertion_function(client: Receiver, commandsSent: []):
            assert [
                "!POWERONMAIN",
                "!POWEROFFMAIN",
                "!POWERONZONE2",
                "!POWEROFFZONE2",
            ] == commandsSent

        await self._test_sending_commands(
            ["!AUDTYPE(PCM zero, 2.0.0)"],
            "AUDTYPE",
            client_functions,
            assertion_function,
            None,
        )
        
    @pytest.mark.asyncio
    async def testtrims(self):

        # check that when we set the trims the receiver gets the correct commands

        def client_functions(client: Receiver):
            client.trim_bass=1.0
            client.trim_centre=-5.0
            client.trim_height=-3.0
            client.trim_lfe=-2.0
            client.trim_surround=5.0
            client.trim_treble=6.0
            
            client.trim_bass_up()
            client.trim_bass_down()
            client.trim_centre_up()
            client.trim_centre_down()   
            client.trim_height_up()
            client.trim_height_down()
            client.trim_lfe_up()
            client.trim_lfe_down()
            client.trim_surround_up()
            client.trim_surround_down()
            client.trim_treble_up()
            client.trim_treble_down()
            


        def assertion_function(client: Receiver, commandsSent: []):
            assert [
                "!TRIMBASS(10)","!TRIMCENTER(-50)","!TRIMHEIGHT(-30)","!TRIMLFE(-20)","!TRIMSURRS(50)","!TRIMTREB(60)",
                "!TRIMBASS+","!TRIMBASS-","!TRIMCENTER+","!TRIMCENTER-","!TRIMHEIGHT+","!TRIMHEIGHT-",
                "!TRIMLFE+","!TRIMLFE-","!TRIMSURRS+","!TRIMSURRS-","!TRIMTREB+","!TRIMTREB-"
            ] == commandsSent

        await self._test_sending_commands(
            ["!AUDTYPE(PCM zero, 2.0.0)"],
            "AUDTYPE",
            client_functions,
            assertion_function,
            None,
        )
    
    @pytest.mark.asyncio
    async def test_power_off(self):
        # make sure POWER(0) turns the API off
        def test_function(client: Receiver):
            assert client.power_on == False


        await self._test_receiving_commands(
            ["!POWER(0)"], "POWER", test_function, None
        )
    
    @pytest.mark.asyncio
    async def test_power_on(self):    
        def test_function(client: Receiver):
            assert client.power_on == True


        await self._test_receiving_commands(
            ["!POWER(1)"], "POWER", test_function, None
        )
            
        
            
            
    @pytest.mark.asyncio
    async def test_basics_volumes_and_mutes(self):
        # Receive a volume level from the processor, and validate our API has determined the volume correctly
        def test_function(client: Receiver):
            assert client.name == "MP-60"
            assert client.volume == -28.1
            assert client.zone_b_volume == -55.0
            assert client.mute_enabled == False
            assert client.zone_b_mute_enabled == True

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function, None
        )

        # check that when we set the volume the receiver gets the correct command

        def client_functions(client: Receiver):
            client.volume = -22
            client.volume_up()
            client.volume_down()
            client.zone_b_volume_up()
            client.zone_b_volume_down()
            client.mute_enabled = True
            client.mute_enabled = False
            client.zone_b_mute_enabled = True
            client.zone_b_mute_enabled = False
            client.lipsync = 10
            client.room_perfect_position = "Focus 1"
            client.voicing = "Voice 1"

        def assertion_function(client: Receiver, commandsSent: []):
            _LOGGER.debug(",".join(commandsSent))
            assert [
                "!VOL(-220)",
                "!VOL+",
                "!VOL-",
                "!ZVOL+",
                "!ZVOL-",
                "!MUTEON",
                "!MUTEOFF",
                "!ZMUTEON",
                "!ZMUTEOFF",
                "!LIPSYNC(10)",
                "!RPFOC(1)",
                "!RPVOI(1)"
            ] == commandsSent

        await self._test_sending_commands(
            ["!AUDTYPE(PCM zero, 2.0.0)"],
            "AUDTYPE",
            client_functions,
            assertion_function,
        )

    @pytest.mark.asyncio
    async def test_notifications(self):
        cc: int = 0

        def notify_me():
            notify_me.counter += 1

        notify_me.counter = 0

        def test_function(client: Receiver):
            assert notify_me.counter == 17

        def before_connect_function(client: Receiver):
            client.register_notification_callback(notify_me)

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function, before_connect_function
        )

    @pytest.mark.asyncio
    async def test_sound_modes_and_sources(self):
        # # Check that the sources are set by the mock processor and the current source is playstation as we will shortly change it
        def test_function(client: Receiver):
            assert len(client.available_sources) == 24
            assert "Playstation" in client.available_sources
            assert len(client.available_sound_modes) == 10
            assert "Party" in client.available_sound_modes
            assert client.sound_mode == "Dolby Upmixer"
            assert client.source == "Apple TV"
            assert client.audio_input == "HDMI"
            assert client.video_input == "HDMI 2"
            assert client.video_information == "2160p50 RGB 4:4:4"
            assert client.audio_information == "PCM zero, 2.0.0"
            assert isinstance(client.available_sound_modes, list)
            assert isinstance(client.available_sources, list)
            assert isinstance(client.zone_b_available_sources, list)
            assert client.zone_b_available_sources == ["Apple TV", "Wonk"]
            assert client.zone_b_source == "Apple TV"
            assert client.available_room_perfect_positions == ["Global", "Focus 1"]
            

        await self._test_receiving_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, test_function
        )

        # Now we set the audio source and make sure that the correct command is sent to the processor
        def test_function(client: Receiver, commandsSent: []):
            assert "!SRC(1)" in commandsSent
            assert "!AUDMODE(9)" in commandsSent
            assert "!ZSRC(1)" in commandsSent

        def client_functions(client: Receiver):
            client.source = "Playstation"
            client.sound_mode = "Party"
            client.zone_b_source = "Wonk"

        await self._test_sending_commands(
            SETUP_RESPONSES, SETUP_LAST_RESPONSE, client_functions, test_function
        )

    async def _test_receiving_commands(
        self,
        commands_received,
        wait_for_command,
        test_function,
        before_connect_function=None,
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

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

        with mock.patch("asyncio.get_event_loop", new_callable=mock.Mock) as debug_mock:
            debug_mock.return_value.create_connection = AsyncMock(
                side_effect=create_conn
            )
            await client.async_connect()
            self.future = asyncio.Future()
            client._api.register_callback(wait_for_command, self._callback)
            protocol.data_received(bytes("\r".join(commands_received) + "\r", "utf-8"))
            await self.future
            test_function(client)
            await client.async_disconnect()

    def _callback(self, param1, param2):
        self.future.set_result(True)

    async def _test_sending_commands(
        self,
        commands_received,
        wait_for_command,
        client_functions,
        test_function,
        before_connect_function=None,
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

        client = await async_create_receiver(FAKE_IP, LyngdorfModel.MP_60)
        if before_connect_function is not None:
            before_connect_function(client)

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
