# Dead GPIOs on this Raspberry Pi 5

**Cause:** 5V backfeed from TB6612FNG motor driver short → RP1 GPIO bank overvoltage

## Fried pins (8 total — bank 20-27)

| GPIO | Physical Pin | Notes |
|------|-------------|-------|
| 20   | 38          |       |
| 21   | 40          |       |
| 22   | 15          |       |
| 23   | 16          |       |
| 24   | 18          |       |
| 25   | 22          |       |
| 26   | 37          |       |
| 27   | 13          |       |

**Do not use any of these pins.** They read LO regardless of output setting or pull-up.

## Motor pin remap

| Signal | Old (dead) | New |
|--------|-----------|-----|
| B PWM  | GPIO 21 (pin 40) | GPIO 4 (pin 7) |
| B IN1  | GPIO 20 (pin 38) | GPIO 17 (pin 11) |
| B IN2  | GPIO 26 (pin 37) | GPIO 5 (pin 29) |

## Spare GPIOs remaining: 9

| GPIO | Physical Pin | Watch out |
|------|-------------|-----------|
| 7    | 26          | SPI0 CE1 |
| 8    | 24          | SPI0 CE0 |
| 9    | 21          | SPI0 MISO |
| 10   | 19          | SPI0 MOSI |
| 11   | 23          | SPI0 SCLK |
| 12   | 32          |           |
| 14   | 8           | UART TX  |
| 15   | 10          | UART RX  |
| 18   | 12          | PCM CLK  |

Another 4 pins (GPIO 0-3) are technically available but have hardware I2C pull-ups and HAT EEPROM — avoid unless you know what you are doing.
