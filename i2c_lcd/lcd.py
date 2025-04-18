# Copyright (c) 2025 James Packer. All rights reserved.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.
#

"""
An interface to an LCD display connected via an I2C port expander, such as the
the DFRobot 20x4 display module: https://www.dfrobot.com/product-590.html.

Currently, the code has only been tested with that display module connected to a
Raspberry Pi.
"""

#
# The output pins on the PCA8574 I2C expander port are connected to the to
# control and data bits on the HD44780U LCD display controller as follows:
#
#    I2C Pin                LCD Controller Function
#      0        RS (register select: 0 for instructions, 1 for data)
#      1        R/Ŵ
#      2        Enable (pulse this to transfer data to/from controller)
#      3        Backlight control (1 to turn it on)
#      7:4      Data bits
#
# These pins are controlled by writing a byte to the I2C address of the port
# expander.
#
# Because only four data bits are used, the LCD controller has to be set to
# 4-bit mode before any other operations can be carried out.
#


# Configure CSpell VSCode plugin
# cSpell:ignore  smbus DDRAM CGRAM
# cSpell:enableCompoundWords

from __future__ import annotations

import enum
from collections import UserList
from enum import Enum, IntEnum
from logging import debug, info, warning
from time import sleep
from typing import Any, Callable, Iterable, SupportsIndex


# pylint: disable=too-many-instance-attributes
class LCD(UserList):
    """
    The LCD class interfaces to the LCD driver via I2C and provides a set of high-level user
    functions to display text, turn the display on and off, etc.

    Args:
        iterable: A list of strings to initialise the display with.
        width: The character width of the display.
        height: The number of lines in the display.
        i2c_address: The address of the display on the I2C bus.
        i2c_bus: The I2C bus that the device is connected to.
    """

    class TruncateMode(Enum):
        """
        How lines longer than the LCD screen are to be handled. One of:

        * `LCD.TruncateMode.TRUNCATE`: Truncate the end of the line to fit the
          screen.
        * `LCD.TruncateMode.ELLIPSIS_END`: Cut the end of the string and append
          the ellipses.
        * `LCD.TruncateMode.ELLIPSIS_MIDDLE`: Show the start and end of the
          string with ellipses in the middle.
        * `LCD.TruncateMode.SCROLL`: Scroll long lines so the whole line is seen
          over time.
        """

        TRUNCATE = enum.auto()
        ELLIPSIS_END = enum.auto()
        ELLIPSIS_MIDDLE = enum.auto()
        SCROLL = enum.auto()

    class Cursor(Enum):
        """
        The style of cursor displayed. One of:

        * `LCD.Cursor.NONE`: No visible cursor
        * `LCD.Cursor.BLINK`: A blinking character cursor
        * `LCD.Cursor.UNDERSCORE`: An underscore cursor
        """

        NONE = enum.auto()
        BLINK = enum.auto()
        UNDERSCORE = enum.auto()

    class _Commands(IntEnum):
        """
        Definitions of command bits. Most functions have a "set" bit to define
        the function and then a number of other bits to define the parameters.
        """

        # fmt: off

        # Clear the display. This is slow (not sure how slow) so needs a delay
        # after executing it
        CLEAR_DISPLAY           = 0b0000_0001
        # Set the cursor (DDRAM address) to 0,0 and undo any shift of the
        # display. The requires about 1.5ms.
        RETURN_HOME             = 0b0000_0011

        # Bits for display entry mode.
        #
        # In "normal" (left to right text) mode, the cursor moves to the right
        # as characters are added. When scroll mode is set, the existing text
        # moves to the left as characters are added, with the cursor remaining
        # where it is. This preserves left to right text. For right to left
        # text, set decrement mode or right scroll. Note that the scroll mode
        # shifts the entire screen contents, not just the current line, so may
        # be of limited use.
        SET_ENTRY_MODE          = 0b0000_0100
        ENTRY_INCREMENT         = 0b0000_0010
        ENTRY_DECREMENT         = 0b0000_0000
        ENTRY_SCROLL_ON         = 0b0000_0001
        ENTRY_SCROLL_RIGHT      = 0b0000_0000
        ENTRY_SCROLL_LEFT       = 0b0000_0010

        # Bits for display modes.
        #
        # Setting the display off hides the content.
        # The cursor is an underline at the next position to be written.
        # Blink flashes the character at the next position to be written.
        SET_DISPLAY_MODE        = 0b0000_1000
        DISPLAY_ON              = 0b0000_0100
        CURSOR_ON               = 0b0000_0010
        BLINK_ON                = 0b0000_0001

        # Bits for display/cursor movement.
        #
        # These are similar to the entry mode settings, but move the cursor or
        # entire display without inserting characters.
        SET_SHIFT_MODE          = 0b0001_0000
        DISPLAY_MOVE            = 0b0000_1000
        CURSOR_MOVE             = 0b0000_0000
        MOVE_RIGHT              = 0b0000_0100
        MOVE_LEFT               = 0b0000_0000

        # Bits to write enable writing CGRAM (character generator memory) and
        # DDRAM (display memory) addresses. The remaining bits in the byte are
        # the address.
        SET_CGRAM_ADDRESS       = 0b0100_0000
        SET_DDRAM_ADDRESS       = 0b1000_0000
        # fmt: on

    # Control bits on the LCD controller, accessed via the I2C expander
    # (PCA8574)

    # fmt: off

    # Register select connected to P0 of expander
    _INSTRUCTION_REGISTER = 0b0000
    _DATA_REGISTER        = 0b0001
    # Read/Write bit connected to P1 of expander
    _READ                 = 0b0010
    _WRITE                = 0b0000
    # Enable bit connected to P2 of expander
    _ENABLE               = 0b0100
    # Backlight control connected to P3 of expander
    _BACKLIGHT_ON         = 0b1000
    _BACKLIGHT_OFF        = 0b0000
    # fmt: on

    def __init__(
        self,
        iterable: Iterable | None = None,
        width: int = 20,
        height: int = 4,
        i2c_address: int = 0x20,
        i2c_bus: int | str = 1,
    ):
        # Initialise LCD controller to default state.

        super().__init__(iterable)

        # Device parameters
        self._display_width = width
        self._display_height = height
        self._i2c_bus = i2c_bus
        self._i2c_address = i2c_address

        # Default display settings
        self._backlight = True
        self._display_on = True
        self._cursor_on = False
        self._blink_on = False
        self._truncate_mode = self.TruncateMode.TRUNCATE
        self._scroll_bar = len(self.data) > self._display_height
        self._current_start_line = 0
        # Flag to indicate that the display may be out of date wrt the data

        # The LCD controller needs at least 15ms after Vcc rises to 4.5V and
        # 40ms after Vcc rises above 2.7V. So wait even though this probably
        # won't be run immediately after power-on.
        sleep(0.04)

        # Configure the interface
        self._function_set()
        self._set_display_mode()
        self._clear_display()
        self._redraw()

    #
    # Intercept standard `list` update methods to redraw the display if the list
    # content is changed.
    #

    def append(self, item: str):
        super().append(item)
        self._redraw()

    def extend(self, other: Iterable):
        super().extend(other)
        self._redraw()

    def insert(self, i: int, item):
        super().insert(i, item)
        self._redraw()

    def remove(self, item):
        super().remove(item)
        self._redraw()

    def pop(self, i: int = -1):
        super().pop(i)
        self._redraw()

    def sort(self, *, key: Callable|None = None, reverse: bool = False):
        super().sort(key=key, reverse=reverse)
        self._redraw()

    def reverse(self):
        super().reverse()
        self._redraw()

    def __setitem__(self, i: SupportsIndex, item):
        super().__setitem__(i, item)
        self._redraw()

    def __delitem__(self, i: SupportsIndex | slice[Any, Any, Any]):
        super().__delitem__(i)
        self._redraw()

    def _function_set(self):
        """
        Set the basic operating function: 4 bit interface and number of display
        lines.
        """

        debug("Function set")

        # After power-on the LCD controller is in 8-bit mode. We need to set it
        # to 4-bit mode because the I2C expander chip uses four bits for data
        # and four bits for control signals.
        #
        # See the HD44780U datasheet (table 12, page 42) for an example of
        # configuring for 4-bit mode. This code doesn't exactly match their
        # example but it seems to work.

        # fmt: off

        # Bits for the function-set command
        SET_FUNCTION_SET = 0b0010_0000
        # DL: Sets the interface data length. Data is sent or received in 8-bit
        # lengths (DB7 to DB0) when DL is 1, and in 4-bit lengths (DB7 to DB4)
        # when DL is 0.
        DL_8_BIT_MODE   = 0b0001_0000
        DL_4_BIT_MODE   = 0b0000_0000
        # N: Sets the number of display lines. Set to 1 for 2- or 4-line
        # displays.
        N_1_LINE        = 0b0000_0000
        N_2_LINES       = 0b0000_1000
        # F: Sets the character font.
        F_5x8           = 0b0000_0000
        F_5x10          = 0b0000_0100
        # fmt: on

        # The comand bit for setting the mode
        command = SET_FUNCTION_SET | DL_4_BIT_MODE | F_5x8
        # The two line display setting is used for anything more than a one-line
        # display. For a 4 x 20 display, for example, it behaves logically as if
        # it were two lines of 40 characters. The first and third line are
        # contiguous (a single "logical" line), as are the second and and fourth
        # lines. This causes some suprising results when wrapping text or moving
        # past the ends of lines.
        if self._display_height == 1:
            command |= N_1_LINE
        else:
            command |= N_2_LINES
        # Set 4 bit mode
        self._lcd_write_byte(0, 0b0001_0010)
        # Set the function-set bits
        self._write_command(command)

    def _set_display_mode(self):
        """
        Set the display mode as defined by the current state.
        """

        # The comand bit for setting the mode
        display_mode = LCD._Commands.SET_DISPLAY_MODE
        # Combine the appropriate bites
        if self._display_on:
            display_mode |= LCD._Commands.DISPLAY_ON
        if self._cursor_on:
            display_mode |= LCD._Commands.CURSOR_ON
        if self._blink_on:
            display_mode |= LCD._Commands.BLINK_ON
        # Write the command
        self._write_command(display_mode)

    def _clear_display(self):
        """
        Clear the display. The cursor is set to the home position (0, 0).
        """

        self._write_command(self._Commands.CLEAR_DISPLAY)
        sleep(0.5)

    def _set_display_address(self, line: int, position: int):
        """
        Set the cursor to a given position.

        Args:
            line: The line number to move to. Line numbers start from 0.
            position: The character position to move to, starting from 0.

        Raises:
            ValueError: If either the line number or character position are out
                        of range.
        """

        # The start address of each line. Note that the third line starts
        # immediately after the first, and the fourth follows on from the
        # second.
        line_addresses = [0x00, 0x40, 0x14, 0x54]

        # Check for valid values
        if not 0 <= line < self._display_height:
            raise ValueError(
                f"Line number ({line}) out of range 0 to {self._display_height-1}"
            )
        if not 0 <= position < self._display_width:
            raise ValueError(
                f"Position ({position}) out of range 0 to {self._display_width-1}"
            )
        # Calculate the memory address for this position.
        address = line_addresses[line] + position
        # Set the current display memory address
        self._write_command(LCD._Commands.SET_DDRAM_ADDRESS | address)

    def _print_at(self, line: int, s: str):
        """
        Print text at a specified location.

        Args:
            line: The line number to write to (lines are numbered from 0).
            position: The character position in the line to start at.
            s: The string to write.
        """

        position = 0
        self._set_display_address(line, position)
        # Note that it is valid to write past the line; it will wrap round
        # to the next line. This may be undesirable in the case of a
        # four-line display where the continuation of a line is not the next
        # line, but the one after.
        for ch in bytearray(s, "ascii"):
            # Write the character to the data memory
            self._write_data(ch)
            # Increment position
            position += 1
            # Don't go outside the diplay window
            if position >= self._display_width:
                break

    def _redraw(self):

        if self._current_start_line > 0:
            up = "^"  # chr(0)
        else:
            up = " "
        if self._current_start_line + self._display_height < len(self.data):
            down = "v"  # chr(1)
        else:
            down = " "

        if (
            self._current_start_line + self._display_height
        ) < 0 or self._current_start_line > len(self.data):
            # Skip updating if nothing will be displayed
            ##self.clear_display()
            info(f"|{'.' * self._display_width}|")
        else:
            info(f"|{'-' * self._display_width}|")

            for display_line in range(self._display_height):
                if not self._scroll_bar:
                    prefix = ""
                elif display_line == 0:
                    prefix = up
                elif display_line == self._display_height - 1:
                    prefix = down
                else:
                    prefix = " "

                text_index = self._current_start_line + display_line
                if 0 <= text_index < len(self.data):
                    text = prefix + self.data[text_index]
                    text = self._truncate(text, self._display_width)
                    self._print_at(display_line, text)
                    info(f"|{text}|")
                else:
                    blank_line = " " * (self._display_width - len(prefix))
                    self._print_at(display_line, prefix + blank_line)
                    info(f"|{' ' * self._display_width}|")
            info(f"|{'-' * self._display_width}|")

    def _truncate(self, text: str, width: int):
        """
        Truncate a line of text to fit in the display. The truncation is done
        according to the current mode.
        """

        # The string or character to use to mark the truncation
        ellipsis = ".."  # chr(2) + chr(2)

        if len(text) <= width:
            # Short strings get padded with spaces to fit the display
            text += " " * (width - len(text))
        elif self._truncate_mode == self.TruncateMode.TRUNCATE:
            # Truncate the text to the display width
            text = text[:width]
        elif self._truncate_mode == self.TruncateMode.ELLIPSIS_END:
            # Cut the end of the string and append the ellipses
            text = text[: width - len(ellipsis)] + "..."
        elif self._truncate_mode == self.TruncateMode.ELLIPSIS_MIDDLE:
            # Show the start and end of the string with ellipses in the middle
            middle = width / 2
            # Round up the length of the first chunk
            first = text[: round(middle + 0.1)]
            # Round down the length of the last chunk
            last = text[-(round(middle - 0.1) - len(ellipsis)) :]
            text = first + ellipsis + last
        elif self._truncate_mode == self.TruncateMode.SCROLL:
            raise NotImplementedError("Scroll mode not implemented")
        else:
            raise ValueError("Unknown truncation mode")

        return text

    #
    # Functions to access the I2C interface
    #

    def _write_command(self, command_bits: int):
        """
        Write a command to the LCD controller instruction register.

        Args:
            command_bits: The 8-bit value to be written to the instruction
                          register.
        """

        debug(f"Command: {command_bits:09_b}")
        self._lcd_write_byte(self._INSTRUCTION_REGISTER, command_bits)

    def _write_data(self, data: int):
        """
        Write to the LCD controller data register.

        Args:
            data: The 8-bit value to be written to the register.
        """

        debug(f"Data: {data:09_b}")
        self._lcd_write_byte(self._DATA_REGISTER, data)

    #
    # Low-level functions to access the LCD controller via I2C
    #

    def _lcd_write_byte(self, register: int, data: int):
        """
        Write a data byte to a register in the LCD controller.

        Args:
            register: Selects either the instruction or data register.
            data: The 8-bit data to write.
        """

        debug(f"write_lcd: {register=}, {data=:09_b}")

        # Data has to be written as two 4-bit values
        lo = data & 0x0F
        hi = data & 0xF0
        # Write the upper bits then the lower bits
        # Data to be written must be in the upper 4 bits
        # Combine the data with the register select bit
        self._lcd_write4(register, hi)
        self._lcd_write4(register, (lo << 4))

    def _lcd_write4(self, register: int, data: int):
        """
        Write 4 bits of data to the LCD controller.

        Args:
            register: Selects either the instruction or data register.
            data: Data in the upper 4 bits of the byte.
        """

        # Combine the register select and write bit with the data
        data |= register | self._WRITE
        # Set the backlight control bit appropriately
        if self._backlight:
            data |= self._BACKLIGHT_ON
        else:
            data |= self._BACKLIGHT_OFF
        # Apply the data to the LCD controller with the Enable bit asserted
        self._i2c_write(data | self._ENABLE)
        # De-assert the Enable bit to complete the write
        self._i2c_write(data)

    def _i2c_write(self, data: int):
        """
        Write one byte to the I2C address.

        Args:
            data: The 8-bit value to write.
        """

        try:
            # pylint: disable=import-outside-toplevel
            from smbus2 import SMBus
        # pylint: disable=bare-except
        except:
            pass
        else:
            with SMBus(bus=self._i2c_bus) as smbus:
                smbus.write_byte(
                    i2c_addr=self._i2c_address,
                    value=data,
                )

    #
    # User level functions
    #

    def define_custom_character(self, code: int, bitmap: list[int]):
        """
        Store the bitmap for a custom character in the character generator RAM.
        See page 13 and table (page 19) of the HD44780 datasheet.

        Args:
            code: The character code. Must be between 0 and 7 (eight characters
                  can be defined).
            bitmap: A list of integers defining the pixels in the character.
        """

        if not 0 <= code < 8:
            raise ValueError("The code for a custom character must be between 0 and 7.")
        if len(bitmap) != 8:
            raise ValueError("The bitmap for a custom character must have eight rows.")

        for row, bits in enumerate(bitmap):
            address = code << 3 | row
            self._write_command(LCD._Commands.SET_CGRAM_ADDRESS | address)
            self._write_data(bits)

    def display_on(self, on: bool):
        """
        Turn the display on or off.

        Args:
            on: If set to True, the display will be on. Otherwise, the
                display will be blanked. (The data is preserved and will be
                visible when the display is turned on again).
        """

        self._display_on = on
        self._set_display_mode()

    def set_cursor(self, style: LCD.Cursor):
        """
        Select the type of cursor to be displayed. Select underline,
        blinking, or no cursor.

        Args:
            style: Specifies the type of cursor to use.
        """

        # Set the appropriate flags for the type of cursor
        if style == LCD.Cursor.NONE:
            # Turn the underline cursor on or off.
            self._cursor_on = False
            self._blink_on = False
        elif style == LCD.Cursor.BLINK:
            self._cursor_on = False
            self._blink_on = True
        elif style == LCD.Cursor.UNDERSCORE:
            self._cursor_on = True
            self._blink_on = False

        # Apply those settings
        self._set_display_mode()

    def backlight_on(self, on: bool):
        """
        Turn the backlight on or off.

        Args:
            on: If set to True, the backlight will be on.
        """

        self._backlight = on
        self._write_command(0)

    def show(self, start_line: int):
        """
        Update the LCD to display the contents of the text buffer, starting at
        `line`.

        Args:
            start_line: The line number in the text buffer to display. Default
                        is zero; i.e. display the first N lines.
        """

        # Don't update if the displayed line has not changed.
        if self._current_start_line == start_line:
            return

        self._current_start_line = start_line

        self._redraw()

    def set_truncate_mode(self, mode: LCD.TruncateMode):
        """
        Set the truncate mode to be used when displaying the text buffer on the
        LCD.
        """

        if self._truncate_mode == self.TruncateMode.SCROLL:
            raise NotImplementedError("Scroll mode not implemented")

        self._truncate_mode = mode

    def assign(self, text: Iterable):
        """
        Assign new data to the text list.
        """
        self.data = list(text)
        self._scroll_bar = len(self.data) > self._display_height
        self._redraw()


if __name__ == "__main__":

    text = [
        "Phasellus id purus a nisl eleifend suscipit feugiat semper ante",
        "Praesent gravida quam non mollis suscipit",
        "Blank line:",
        "",
        "1234567890123456789",
        "12345678901234567890",
        "123456789012345678901",
        "Nullam a tellus rutrum, congue lectus et, feugiat lacus",
        # "Nam id mauris egestas neque imperdiet gravida",
        # "Etiam a nunc cursus odio placerat ultricies nec et ligula",
        # "Ut a dui ut justo commodo pellentesque eget sed justo",
        # "Praesent pellentesque neque euismod massa rutrum iaculis",
        # "Fusce at tortor a lacus malesuada placerat",
    ]

    chars = [
        [
            0b00100,
            0b01110,
            0b11111,
            0b00000,
            0b00100,
            0b01110,
            0b11111,
            0b00000,
        ],
        [
            0b00000,
            0b11111,
            0b01110,
            0b00100,
            0b00000,
            0b11111,
            0b01110,
            0b00100,
        ],
        [
            0b00000,
            0b00000,
            0b00000,
            0b00000,
            0b11011,
            0b00000,
            0b00000,
            0b00000,
        ],
    ]

    lcd = LCD()
    lcd.assign(text)

    for n, bitmap in enumerate(chars):
        lcd.define_custom_character(n, bitmap)

    lcd.insert(5, "Inserted: Quisque elementum magna a dignissim tristique.")

    lcd.set_truncate_mode(LCD.TruncateMode.ELLIPSIS_MIDDLE)
    for n in range(-4, len(text) + 5):
        lcd.show(n)
        sleep(0.8)
    lcd.display_on(False)
    lcd.backlight_on(False)
