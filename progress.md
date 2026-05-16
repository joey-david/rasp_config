# Building the robot

### Pre May 15th, 2026:

Struggled to set up bookwork via usb since I didn't have a microsd. At first it wouldn't even boot and it would display a boot image error, via fourfold fast flashing of the green ACT light. I finally succeeded in finding a working USB, after which I modified the bookworm image with a launch script that automatically enabled SSH and connected to my home Wi-Fi so that I could set it up without plugging in a keyboard or display, over ssh.

### May 15th, 2026

Received the camera and microsd. Microsd doesn't work, it's counterfeit :/. Camera does work though - I set up a web ui app to see what it sees easily over ssh, including image inversion and fisheye correction parameters.
- ReSpeaker 2-mic HAT: the stock WM8960 path failed on reset; switching to the board-specific `seeed-2mic-voicecard` overlay plus a kernel-matched WM8960 module exposed ALSA capture on `card 1`, and the camera UI now records synced audio+video `.mkv` files.
