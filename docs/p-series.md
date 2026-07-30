# P100 / P200 / P300 External Control Manual

Steinway Lyngdorf multichannel surround sound processors (also covers the
Head Unit variant, which shares this protocol with a different volume/gain
range - see Values column).

## Connection

- Network: TCP port 84 (Bonjour service "slactrl", also reachable at http://p100.local / http://p200.local / http://p300.local / http://headunit.local)
- Serial: DTE wiring (needs null modem + gender changer), 8 data bits, no parity, 1 stop bit, 115200 baud, no hardware handshake
- Command framing: every command starts with `!` and ends with `<CR>` (0x0D). Status requests end with `?`. Malformed commands are ignored.
- Feedback levels via `!VERB(X)<CR>` (X = 0, 1, or 2): 0 = reply only when queried; 1 = also pushes a status message whenever it changes; 2 = also echoes each command back prefixed with `#` instead of `!`.
- Note: from deep sleep standby, the device may miss the first character(s) sent - send the ON command a couple of times to be sure.
- No streaming source, channel trims (bass/treble/center/height/LFE/surround), or balance control exist in this protocol - this processor family relies on external sources and does not expose tone/channel trims over serial.

## Commands

| Command | Reply | Values | Description |
|---|---|---|---|
| `!AUDIN ?` | `!AUDIN(X)` | X is the number of the active audio input - see list | Returns currently selected audio input |
| `!AUDIO` | | | Audio button |
| `!AUDMODE-` | | | Audio processing mode down button |
| `!AUDMODE ?` | `!AUDMODE(X)` | X is the number of the currently active audio mode | Request audio processing mode |
| `!AUDMODE(X)` | | X is any of the numbers returned from `!AUDMODEL ?` | Set audio processing mode |
| `!AUDMODE+` | | | Audio processing mode up button |
| `!AUDMODEL ?` | `!AUDMODECOUNT(N)` then `!AUDMODE(X)"name"` repeated for each available mode | N is the total number of available audio modes; X is the mode number; name is a string describing mode X | Get list of audio processing modes |
| `!AUDTYPE ?` | `!AUDTYPE(name)` | name is a string describing the current audio input type | Get input audio type (still not final format) |
| `!BACK` | | | Back button |
| `!DEFVOL ?` | `!DEFVOL(X)` | -550 to -200 (= -99.0 to -20.0 dB); Head Unit: 300 to 680 (= 30.0 to 68.0 dB); MP-60/MP-50AES: -550 to 0 | Requests default volume setting |
| `!DEFVOL(OFF)` | | | Turns off default volume (uses last used volume on boot instead) |
| `!DEFVOL(X)` | | Same ranges as `!DEFVOL ?` | Sets default volume |
| `!DEVICE ?` | `!DEVICE(name)` | e.g. `!DEVICE(P300)` for P300 | Returns the name of the device |
| `!DIM-` | | | Reduce brightness of the VFD display |
| `!DIM ?` | `!DIM(X)` | 0 = 100%, 1 = 75%, 2 = 50%, 3 = 25% | Request brightness of the VFD display |
| `!DIM(X)` | | 0 = 100%, 1 = 75%, 2 = 50%, 3 = 25% | Set brightness of the VFD display |
| `!DIM+` | | | Increase the brightness of the VFD display |
| `!DIRD` | | | Direction Down button |
| `!DIRL` | | | Direction Left button |
| `!DIRR` | | | Direction Right button |
| `!DIRU` | | | Direction Up button |
| `!DTSDIALOG ?` | `!DTSDIALOG(X)` | X = current setting, signed value / 10 (e.g. -10 = -1.0 dB) | Request the current setting of DTS Dialog Control |
| `!DTSDIALOGAVAILABLE ?` | `!DTSDIALOGAVAILABLE(X)` | X = 0: not available, otherwise X = 1 | Request the current availability of DTS Dialog Control |
| `!DTSDIALOGDN` | | | DTS Dialog Control down |
| `!DTSDIALOGUP` | | | DTS Dialog Control up |
| `!ENTER` | | | Enter button |
| `!EXIT` | | | Exit button |
| `!HDMIMAINOUT ?` | `!HDMIMAINOUT(X)` | X is the number of the HDMI output - see list | Requests which HDMI output is used for main out |
| `!HDMIMAINOUT(X)` | | X is the number of the HDMI output - see list | Selects which HDMI output to use for main out (P200 only) |
| `!HDMIMATRIXMODE ?` | | | Requests the current state of HDMI-matrix mode |
| `!HDMIMATRIXMODEOFF` | | | Sets HDMI-matrix mode OFF |
| `!HDMIMATRIXMODEON` | | | Sets HDMI-matrix mode ON |
| `!HDMIOUT1(X)` | | X is the number of the HDMI input to route - see list | Route HDMI input X to HDMI output 1 (overridden by source select if this is the main output) |
| `!HDMIOUT2(X)` | | X is the number of the HDMI input to route - see list | Route HDMI input X to HDMI output 2 |
| `!HDMIOUT3(X)` | | X is the number of the HDMI input to route - see list | Route HDMI input X to HDMI output 3 |
| `!HDMIOUT4(X)` | | X is the number of the HDMI input to route - see list | Route HDMI input X to HDMI output 4 |
| `!HDMIOUT5(X)` | | X is the number of the HDMI input to route - see list | Route HDMI input X to HDMI output 5 |
| `!INFO` | | | Info button |
| `!INTERFACE ?` | `!INTERFACE(IP)` or `!INTERFACE(SERIAL)` | | Returns the active interface for this section |
| `!LIPSYNC-` | | | Reduces the lipsync value |
| `!LIPSYNC ?` | `!LIPSYNC(X)` | X is the current lipsync trim in ms | Requests the lipsync value |
| `!LIPSYNC(X)` | | X is in the range returned by `!LIPSYNCRANGE ?` | Sets the lipsync value |
| `!LIPSYNC+` | | | Increases the lipsync value |
| `!LIPSYNCRANGE ?` | `!LIPSYNCRANGE(min,max)` | | Returns the valid range for lipsync values |
| `!LOUDNESS ?` | `!LOUDNESS(X)` | 0 (off) or 1 (on) | Requests loudness status |
| `!LOUDNESS(X)` | | 0 (off) or 1 (on) | Sets loudness status |
| `!MAXVOL ?` | `!MAXVOL(X)` | -550 to 240 (= -55.0 to +24.0 dB); Head Unit: 300 to 999 (= 30.0 to 99.9 dB) | Requests the maximum volume setting |
| `!MAXVOL(X)` | | Same ranges as `!MAXVOL ?` | Sets the maximum volume |
| `!MENU` | | | Menu button |
| `!MULTIVIEW` | | | Multiview button (same as "PiP" on remote, P200 only) |
| `!MUTE` | | | Mute toggle button |
| `!MUTE ?` | `!MUTEON` or `!MUTEOFF` | | Requests mute |
| `!MUTEOFF` | | | Mute off |
| `!MUTEON` | | | Mute on |
| `!MVIEW(X)` | | 0 to 5 (0 = off, 1-5 = layout) | Selects Multiview layout X, or turns off multiview if X is 0 |
| `!MVIEW ?` | `!MVIEW(X)` | 0 to 5 (0 = off, 1-5 = layout) | Returns currently active multiview layout (0 if off) |
| `!MVIEWACTIVE(X)` | | 1 to 4 (window number) | Sets active multiview window |
| `!MVIEWACTIVE ?` | `!MVIEWACTIVE(X)` | 1 to 4 (window number) | Returns active multiview window |
| `!MVIEWSRC ?` | | Indexes from the source list | Returns the 4 sources in the multiview windows |
| `!NEXT` | | | Next button |
| `!NUM(X)` | | 0 to 9 | Numeric buttons |
| `!PING ?` | | | Ping |
| `!PLAY` | | | Play button |
| `!POWER ?` | `!POWER(X)` | 0 (standby) or 1 (on) | Requests power status |
| `!POWEROFFMAIN` | | | Power off |
| `!POWEROFFZONE2` | | | Zone B power off |
| `!POWERONMAIN` | | | Power on |
| `!POWERONZONE2` | | | Zone B power on |
| `!POWERZONE2 ?` | `!POWERZONE2(X)` | 0 (off) or 1 (on) | Requests power status for Zone B |
| `!PREV` | | | Previous button |
| `!RPFOC-` | | | Previous RoomPerfect position button |
| `!RPFOC ?` | `!RPFOC(X)` | X is current position (0=bypass, 1-4=focus1-4, 9=global) | Request RoomPerfect position |
| `!RPFOC(X)` | | X is position to select (0=bypass, 1-4=focus1-4, 9=global) | Set RoomPerfect position |
| `!RPFOC+` | | | Next RoomPerfect position button |
| `!RPFOCS ?` | `!RPFOCCOUNT(N)` then `!RPFOC(X)"name"` repeated for each available position | N is the total number of positions; X is the position number; name is a string. Global and bypass count as positions | Get available RoomPerfect positions |
| `!RPVOI-` | | | Previous voicing button |
| `!RPVOI ?` | `!RPVOI(X)` | X is the currently selected voicing (from `!RPVOIS ?`) | Request active voicing |
| `!RPVOI(X)` | | X is the voicing to select (from `!RPVOIS ?`) | Set voicing |
| `!RPVOI+` | | | Next voicing button |
| `!RPVOIS ?` | `!RPVOICOUNT(N)` then `!RPVOI(X)"name"` repeated for each available voicing | N is the total number of voicings; X is the voicing number; name is a string | Request list of available voicings |
| `!SETUP` | | | Setup button |
| `!SPKCONF ?` | `!SPKCONF(X)` | X is a value from `!SPKCONFS ?` | Requests the index of the current speaker config |
| `!SPKCONF(X)` | | X is a value from `!SPKCONFS ?` | Selects a speaker config |
| `!SPKCONFS ?` | `!SPKCONFCOUNT(N)` then per-config entries | N is the total number of available speaker configs; X is the config number; name is a string | Requests a list of speaker configs |
| `!SRC-` | | | Previous source button |
| `!SRC ?` | `!SRC(X)"Name"` | X is the number of the currently selected source; Name is the source's name | Request active source |
| `!SRC(X)` | | X is the source to select (from `!SRCS ?`) | Select source |
| `!SRC(X) ?` | `!SRC(X)"Name"` | X is the number of the requested source; Name is the source's name | Get info for source X |
| `!SRC+` | | | Next source button |
| `!SRCBTN` | | | SRC button on the P200 remote |
| `!SRCOFF-` | | | Decrease source volume offset |
| `!SRCOFF ?` | `!SRCOFF(X)` | X is the volume offset for the current source, -100 (=-10dB) to 100 (=+10dB) | Request source volume offset for current source |
| `!SRCOFF(X)` | | X is the new volume offset for the current source, -100 (=-10dB) to 100 (=+10dB) | Set source volume offset for current source |
| `!SRCOFF+` | | | Increase source volume offset |
| `!SRCS ?` | `!SRCCOUNT(N)` then `!SRC(X)"Name"` repeated for each available source | N is the number of sources; X is the source number; Name is a string | Request list of available sources |
| `!STANDBYLEVEL ?` | `!STANDBYLEVEL(X)` | X=0 for deep sleep, X=1 for network standby | Requests current setting for standby level |
| `!VERB ?` | `!VERB(X)` | 0 to 2 | Request verbosity level of active interface |
| `!VERB(X)` | | 0 to 2 | Set verbosity level of active interface |
| `!VIDIN ?` | `!VIDIN(X)` | X is the selected video input - see list | Returns currently selected video input |
| `!VIDTYPE ?` | `!VIDTYPE(typestring)` | | Returns a string with the current video input format |
| `!VOL-` | | | Decrease volume |
| `!VOL-(X)` | | -999 to 240 (= -99.9 to +24.0 dB); Head Unit: 0 to 999 (= 0 to 99.9 dB) | Decrease volume by X |
| `!VOL ?` | `!VOL(X)` | Same ranges as `!VOL-(X)` | Request current volume |
| `!VOL(X)` | | Same ranges as `!VOL-(X)` | Set volume to X |
| `!VOL+` | | | Increase volume |
| `!VOL+(X)` | | Same ranges as `!VOL-(X)` | Increase volume by X |
| `!ZAUDIN ?` | `!ZAUDIN(X)` | X is the selected Zone B audio input - see list | Returns currently selected Zone B audio input |
| `!ZMUTE` | | | Toggle Zone B mute |
| `!ZMUTE ?` | | | Request Zone B mute |
| `!ZMUTEOFF` | | | Zone B mute off |
| `!ZMUTEON` | | | Zone B mute on |
| `!ZSRC-` | | | Previous Zone B source button |
| `!ZSRC ?` | `!ZSRC(X)"Name"` | X is the number of the currently selected source; Name is the source's name | Request current Zone B source |
| `!ZSRC(X)` | | X is the source to select (from `!ZSRCS ?`) | Set Zone B source |
| `!ZSRC(X) ?` | `!ZSRC(X)"Name"` | X is the number of the requested source; Name is the source's name | Request info about Zone B source X |
| `!ZSRC+` | | | Next Zone B source button |
| `!ZSRCS ?` | `!ZSRCCOUNT(N)` then `!ZSRC(X)"Name"` repeated for each source | N is the number of Zone B sources; X is the source number; Name is a string | Get list of available Zone B sources |
| `!ZVOL-` | | | Decrease Zone B volume |
| `!ZVOL-(X)` | | -999 to 240 (= -99.9 to +24.0 dB); Head Unit: 0 to 999 (= 0 to 99.9 dB) | Decrease Zone B volume by X |
| `!ZVOL ?` | `!ZVOL(X)` | Same ranges as `!ZVOL-(X)` | Request current Zone B volume |
| `!ZVOL(X)` | | Same ranges as `!ZVOL-(X)` | Set Zone B volume |
| `!ZVOL+` | | | Increase Zone B volume |
| `!ZVOL+(X)` | | Same ranges as `!ZVOL-(X)` | Increase Zone B volume by X |

## Automatic Status Messages

When feedback level 1 or higher is active, these statuses push automatically on change (same command as their query form): Audio input, Audio processing mode, Audio type, Mute, Power, RP Focus Position, Voicing, Source, Video input, Video type, Volume, Multiview layout, Multiview active window, Multiview sources, Zone power, Zone audio input, Zone source, Zone user mute, Zone volume.

## Appendices

### Audio Inputs

| No. | Audio Input |
|---|---|
| 0 | None |
| 1 | HDMI |
| 2 | 8 Channel Analog |
| 3 | Spdif 1 (Optical) |
| 4 | Spdif 2 (Optical) |
| 5 | Spdif 3 (Optical) |
| 6 | Spdif 4 (Optical) |
| 7 | Spdif 5 (AES) |
| 8 | Spdif 6 (Coax) |
| 9 | Spdif 7 (Coax) |
| 10 | Spdif 8 (Coax) |
| 11 | Internal Player |
| 12 | USB |
| 13 | Analog 1 (Unbalanced) |
| 14 | Analog 2 (Unbalanced) |
| 15 | Analog 3 (Unbalanced) |
| 16 | Analog 4 (Unbalanced) |
| 17 | Analog 5 (Balanced) |
| 18-19 | Reserved, do not use |
| 20 | 16-Channel Input (optional for P200/P300) |
| 21 | Audio Return Channel |

### Video Inputs

| No. | Video Input |
|---|---|
| 0 | None |
| 1 | HDMI 1 |
| 2 | HDMI 2 |
| 3 | HDMI 3 |
| 4 | HDMI 4 |
| 5 | HDMI 5 (P200/P300 only) |
| 6 | HDMI 6 (P200/P300 only) |
| 7 | HDMI 7 (P200/P300 only) |
| 8 | HDMI 8 (P200/P300 only) |
| 9 | Internal (P200/P300 only) |

### Video Outputs (P200/P300 only)

| No. | Video Output |
|---|---|
| 0 | None |
| 1 | HDMI Out 1 |
| 2 | HDMI Out 2 |
| 3 | HDMI Out 3 |
| 4 | HDMI Out 4 |
| 5 | HDBT Out |
| 6 | Reserved, do not use |
| 7 | Video Wall |

## IR Codes

NEC Protocol

| Description | Value |
|---|---|
| 0 | 0x37CA, 0x00FF |
| 1 | 0x37CA, 0x01FE |
| 2 | 0x37CA, 0x02FD |
| 3 | 0x37CA, 0x03FC |
| 4 | 0x37CA, 0x04FB |
| 5 | 0x37CA, 0x05FA |
| 6 | 0x37CA, 0x06F9 |
| 7 | 0x37CA, 0x07F8 |
| 8 | 0x37CA, 0x08F7 |
| 9 | 0x37CA, 0x09F6 |
| Audio | 0x37CA, 0x0AF5 |
| Setup | 0x37CA, 0x0BF4 |
| Power Toggle | 0x37CA, 0x0CF3 |
| Power On | 0x37CA, 0x807F |
| Power Off | 0x37CA, 0x817E |
| PiP | 0x37CA, 0x0DF2 |
| Previous | 0x37CA, 0x0EF1 |
| Play_Pause | 0x37CA, 0x0FF0 |
| Next | 0x37CA, 0x10EF |
| Up | 0x37CA, 0x11EE |
| Left | 0x37CA, 0x12ED |
| OK | 0x37CA, 0x13EC |
| Right | 0x37CA, 0x14EB |
| Down | 0x37CA, 0x15EA |
| Back | 0x37CA, 0x16E9 |
| Menu | 0x37CA, 0x17E8 |
| SRC | 0x37CA, 0x18E7 |
| Vol+ | 0x37CA, 0x19E6 |
| SRC+ | 0x37CA, 0x1AE5 |
| Vol- | 0x37CA, 0x1BE4 |
| Mute | 0x37CA, 0x1CE3 |
| SRC- | 0x37CA, 0x1DE2 |
| Source 0 | 0x37CA, 0x718E |
| Source 1 | 0x37CA, 0x728D |
| Source 2 | 0x37CA, 0x738C |
| Source 3 | 0x37CA, 0x748B |
| Source 4 | 0x37CA, 0x758A |
| Source 5 | 0x37CA, 0x7689 |
| Source 6 | 0x37CA, 0x7788 |
| Source 7 | 0x37CA, 0x7887 |
| Source 8 | 0x37CA, 0x7986 |
