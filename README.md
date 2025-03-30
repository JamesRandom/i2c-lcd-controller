# I2C LCD Controller

A Python interface to an LCD display module connected via an I2C port expander, such as the
the DFRobot 20x4 display module: https://www.dfrobot.com/product-590.html.

Currently, the code has only been tested with that display module connected to a
Raspberry Pi.

I bought the display for a possible project using the Raspberry Pi, but then
found that the only code they supply is in C for the Arduino (which depend on
other hardware interface libraries). Rather than try and rewrite their library
in Python, I decided it was better to look at the datasheets and write a simple
interface class.

## Documentation

* [I2C LCD API documentation](https://jamesrandom.github.io/i2c-lcd-controller/)

## Installation

```bash
$ python3 -m venv .venv
$ source .venv/bin/activate
$ python3 -m pip install https://github.com/JamesRandom/i2c-lcd-controller
```

### Requirements

* Python version 3.9 or later (it may work with earlier versions but it isn't tested)

* Requires a compatible SMBus interface, such as [smbus2](https://pypi.org/project/smbus2/)

### Enable I2C interface on Raspberry Pi

On the Raspberry Pi, you will need to enable the I2C interface. This can be done in any of the following ways:

*   Using the configuration tool (select "Interface Options" then "I2C"):

        ```bash
        $ sudo raspi-config
        ```

*   From the command line:

        ```bash
        $ sudo raspi-config nonint do_i2c 0
        ```

*   By changing the following line in `/boot/config.txt` and then rebooting:

        ```bash
        dtparam=i2c_arm=on
        ```
