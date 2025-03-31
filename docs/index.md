# Liquid crystal display controller

This module allows a Python program to access an alphanumeric liquid crystal display (LCD)
module, that uses the Hitachi HD44780, or compatible, LCD controller.

The code is only suitable for an LCD that is connected via an I<sup>2</sup>C interface,
for example the [DFRobot 20×4 display
module](https://www.dfrobot.com/product-590.html) and similar products. It
cannot be used in a system where the LCD controller is connected directly to the
microcontroller's GPIO pins.

The code was written to be used with a Raspberry Pi. It should be compatible
with other microcontrollers such as Arduino, but this has not been tested

It turns out there are lots of Python implementations of LCD controllers, of
varying degrees of completeness. If you are looking for something more flexible
and fully functional, then take a look at
[RPLCD](https://rplcd.readthedocs.io/). I haven't tried this but I probably
would have used it, instead of writing my own code, if I had seen it sooner.

## Features

* Simple API

* Support for:

    * printing text at any location
    * turn display and backlight on/off
    * select cursor type
    * clearing display
    * clearing a single line

**To do list:**

* Support newline characters in text (and maybe an explicit newline method)
* Cache the display contents in a framebuffer so only changes to the content
    need to be written to the display
* With that, could make the display a window onto a larger virtual screen to
    enable more efficient vertical and horizontal scrolling of text (including
    scrolling single lines)
* Add support for custom characters

## Installation

You can install from the GitHub repository, for example:

```bash
$ pip install git+https://github.com/JamesRandom/i2c-lcd-controller.git
```

Alternatively, you can clone the repository and install from source:

```bash
$ git clone https://github.com/JamesRandom/i2c-lcd-controller.git
$ pip install ./i2c-lcd-controller
```

## Example

```{python}
from time import sleep

from i2c_lcd import LCD

lcd = LCD()

lcd.clear_display()

# Print some text
lcd.move_to(0, 5)
lcd.print("Hello world")
sleep(1)

# Show the various cursor types
lcd.set_cursor(LCD.Cursor.BLINK)
sleep(1)
lcd.set_cursor(LCD.Cursor.UNDERSCORE)
sleep(1)
lcd.set_cursor(LCD.Cursor.NONE)
sleep(1)

# Display more text and delete the original
lcd.move_to(1, 6)
lcd.print("Hello world")
lcd.clear_line(0)

# Turn off display and backlight
sleep(3)
lcd.display(False)
sleep(2)
lcd.backlight(False)
```

## Hardware

The output pins on the PCA8574 I<sup>2</sup>C expander port are connected to the
control and data bits on the HD44780U LCD controller as follows:

| Expander Port Pin | LCD Controller Function                                 |
| ----------------- | ------------------------------------------------------- |
| 0                 | RS (register select: 0 for instructions, 1 for data)    |
| 1                 | R/W̅                                                     |
| 2                 | Enable (pulse this to transfer data to/from controller) |
| 3                 | Backlight control (1 to turn it on)                     |
| 7:4               | Data bits                                               |

These pins are controlled by writing a byte with the signal values to the I<sup>2</sup>C
address of the port expander.

To write a value to the LCD controller, two writes to the I<sup>2</sup>C interface
are required: once with the Enable bit high and then with the Enable bit low in
order to latch the data into the controller.

To write a byte to the LCD controller, two four bit values have to be written
(high-order bits first). Therefore, this requires a total of four I<sup>2</sup>C writes.

### Datasheets

* [HD44780U Dot Matrix Liquid Crystal Display Controller/Driver](https://cdn-shop.adafruit.com/datasheets/HD44780.pdf)
* [PCA8574/74A Remote 8-bit I/O expander for I2C-bus](https://www.nxp.com/docs/en/data-sheet/PCA8574_PCA8574A.pdf)
