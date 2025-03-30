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

from enum import IntEnum
from logging import debug, warning
from time import sleep

from smbus2 import SMBus


# pylint: disable=too-many-instance-attributes
class LCD:
    """
    The LCD class interfaces to the LCD driver via I2C and provides a set of high-level user
    functions to display text, turn the display on and off, etc.

    Args:
        size: A tuple of character width and number of lines in the display.
        i2c_address: The address of the display on the I2C bus.
        i2c_bus: The I2C bus that the device is connected to.
    """

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

    _X = 0
    _Y = 1

    def __init__(
        self,
        size: tuple[int, int] = (20, 4),
        i2c_address: int = 0x20,
        i2c_bus: int | str = 1,
    ):
        # Initialise LCD controller to default state.

        # Device parameters
        self._display_size = size
        self._i2c_bus = i2c_bus
        self._i2c_address = i2c_address

        # Default display settings
        self._backlight = True
        self._display_on = True
        self._cursor_on = False
        self._blink_on = False
        self._scroll_mode = False
        self._left_to_right = True

        # Current cursor position
        self._cursor = [0, 0]

        # The LCD controller needs at least 15ms after Vcc rises to 4.5V and
        # 40ms after Vcc rises above 2.7V. So wait even though this probably
        # won't be run immediately after power-on.
        sleep(0.04)

        # Configure the interface
        self._function_set()
        self._set_display_mode()
        self._set_entry_mode()

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
        # contiguous (a single "logical" line), and the second and and fourth
        # lines are contiguous. This causes some suprising results when moving
        # past the ends of lines.
        if self._display_size[self._Y] == 1:
            command |= N_1_LINE
        else:
            command |= N_2_LINES
        # Set 4 bit mode
        self._lcd_write(0, 0b001_0010)
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

    def _set_entry_mode(self):
        """
        Set the entry mode as defined by the current state.
        """

        # The comand bit for setting the mode
        entry_mode = LCD._Commands.SET_ENTRY_MODE
        # Combine the appropriate bits
        if self._scroll_mode:
            entry_mode |= LCD._Commands.ENTRY_SCROLL_ON
        if self._left_to_right:
            entry_mode |= LCD._Commands.ENTRY_SCROLL_LEFT
        # Write the command
        self._write_command(entry_mode)

    #
    # User level functions
    #

    def scroll_left(self, count: int):
        """
        Scroll the display right by the specified number of places. See the
        description of `scroll_mode()` for more information.

        Args:
            count: Number of character positions to scroll. The text wraps round
                   at the ends of lines.
        """
        command = (
            LCD._Commands.SET_SHIFT_MODE
            | LCD._Commands.DISPLAY_MOVE
            | LCD._Commands.MOVE_LEFT
        )
        for _ in range(count):
            self._write_command(command)

    def scroll_right(self, count: int):
        """
        Scroll the display right by the specified number of places. See the
        description of `scroll_mode()` for more information.

        Args:
            count: Number of character positions to scroll. The text wrap round
                   at the ends of lines.
        """

        command = (
            LCD._Commands.SET_SHIFT_MODE
            | LCD._Commands.DISPLAY_MOVE
            | LCD._Commands.MOVE_RIGHT
        )
        for _ in range(count):
            self._write_command(command)

    def left_to_right(self, on: bool):
        """
        Set text insertion direction.

        Args:
            on: If True, text will be written left-to-right. If False, then text
                will be written right-to-left.
        """

        self._left_to_right = on
        self._set_entry_mode()

    def scroll_mode(self, on: bool):
        """
        Turn on scrolling mode for text entry. When this is one, then new
        characters are entered at the cursor position and the existing text is
        shifted left (or right, depending on the setting of left-to-right text mode).

        Note that the entire display is shifted, not just the current line. Text
        shifted off either end of the line wraps around to the previous/next
        line. For a four-line display, this results in some odd effects because,
        for example, the end of the first line wraps to the start of the third
        line.

        Args:
            on: If True, turn on scroll mode. Otherwise use cursor
                increment/decrement mode.
        """

        self._scroll_mode = on
        self._set_entry_mode()

    def display(self, on: bool):
        """
        Turn the display on or off.

        Args:
            on: If set to True, the display will be on. Otherwise, the
                display will be blanked. (The data is preserved and will be
                visible when the display is turned on again).
        """

        self._display_on = on
        self._set_display_mode()

    def cursor(self, on: bool):
        """
        Turn the underline cursor on or off.

        Args:
            on: If set to True, the cursor will be on.
        """

        self._cursor_on = on
        self._set_display_mode()

    def blink(self, on: bool):
        """
        Turn the blinking character cursor on or off.

        Args:
            on: If set to True, blinking will be on.
        """

        self._blink_on = on
        self._set_display_mode()

    def backlight(self, on: bool):
        """
        Turn the backlight on or off.

        Args:
            on: If set to True, the backlight will be on.
        """

        self._backlight = on
        self._write_command(0)

    def clear_display(self):
        """
        Clear the display.
        """

        self._write_command(self._Commands.CLEAR_DISPLAY)
        sleep(0.5)

    def home(self):
        """
        Return the cursor to the home position (0, 0) and undo any shifts of
        the display.
        """

        self._write_command(self._Commands.RETURN_HOME)
        sleep(0.0015)

    def move_to(self, line: int, position: int):
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
        if not 0 <= line < self._display_size[self._Y]:
            raise ValueError(
                f"Line number ({line}) out of range 0 to {self._display_size[self._Y]-1}"
            )
        if not 0 <= position < self._display_size[self._X]:
            raise ValueError(
                f"Position ({position}) out of range 0 to {self._display_size[self._X]-1}"
            )
        # Calculate the memory address for this position.
        address = line_addresses[line] + position
        # Set the current display memory address
        self._write_command(LCD._Commands.SET_DDRAM_ADDRESS | address)
        # Update our internal record of the cursor position
        self._cursor = [position, line]

    def print(self, s: str):
        """
        Write text to the display.

        Args:
            s: The string to write.
        """

        for c in s:
            # If position is off either end of the line, then stop. Note that it
            # is valid to write past the line; it will wrap round to the next
            # line. But, in general, that may not be what we want. Particularly
            # in the case of a four-line display where the continuation of a
            # line is not the next line, but the one after.
            if not 0 <= self._cursor[self._X] < self._display_size[self._X]:
                break
            # Write the character to the data memory
            self._write_data(ord(c) & 0xFF)
            # Adjust our internal record of the position depending on the
            # insertion direction
            if self._left_to_right:
                self._cursor[self._X] += 1
            else:
                self._cursor[self._X] -= 1

    def print_at(self, line: int, position: int, s: str):
        """
        Print text at a specified location. Just a shortcut for [`move_to()`][i2c_lcd.LCD.move_to] and
        [`print()`][i2c_lcd.LCD.print].

        Args:
            line: The line number to write to (lines are numbered from 0).
            position: The character position in the line to start at.
            s: The string to write.
        """

        self.move_to(line, position)
        self.print(s)

    def clear_line(self, character: str = " "):
        """
        Erase the contents of the current line. Does not change the cursor position.

        Args:
            character: The character to use to overwrite the current content.
                       Defaults to a space.
        """

        # Record the current position
        pos = self._cursor[self._X]
        # Set the cursor to the start of the line
        self.move_to(self._cursor[self._Y], 0)
        # Fill the line
        for _ in range(self._display_size[self._Y]):
            self._write_data(ord(character) & 0xFF)
        # Restore the original cursor position
        self.move_to(self._cursor[self._Y], pos)

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
        self._lcd_write(self._INSTRUCTION_REGISTER, command_bits)

    def _write_data(self, data: int):
        """
        Write to the LCD controller data register.

        Args:
            data: The 8-bit value to be written to the register.
        """

        debug(f"Data: {data:09_b}")
        self._lcd_write(self._DATA_REGISTER, data)

    #
    # Low-level functions to access the LCD controller via I2C
    #

    def _lcd_write(self, register: int, data: int):
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

    def lcd_read(self, register: int) -> int:
        """
        Read a data byte from a register in the LCD controller.

        NOTE:
            Not currently working as expected. Haven't spent any time
            investigating, as I don't have a use for it at the moment.

        Args:
            register: Selects either the instruction or data register.

        Returns:
            A byte of data from the controller.
        """

        # Read the upper 4 bits
        hi = self._lcd_read4(register)
        # Then the lower 4 bits
        lo = self._lcd_read4(register)
        # Combine them (both nibbles are in the upper 4 bits) into a byte
        data = hi | (lo >> 4)

        return data

    def _lcd_read4(self, register: int) -> int:
        """
        Read 4 bits from a register in the LCD controller.

        Args:
            register: Selects either the instruction or data register.

        Returns:
            A byte with the controller data in the upper 4 bits.
        """

        # Combine the register and read bit
        control_bits = register | self._READ
        # Set the backlight control bit appropriately
        if self._backlight:
            control_bits |= self._BACKLIGHT_ON
        else:
            control_bits |= self._BACKLIGHT_OFF
        # Assert enable bit
        self._i2c_write(control_bits | self._ENABLE)
        # De-assert enable bit
        self._i2c_write(control_bits)
        # Read the data
        data = self._i2c_read() & 0xF0

        return data

    #
    # Functions to access the I2C interface
    #

    def _i2c_read(self) -> int:
        """
        Read one byte from the I2C address.
        """

        with SMBus(bus=self._i2c_bus) as smbus:
            data = smbus.read_byte(
                i2c_addr=self._i2c_address,
            )

        return data

    def _i2c_write(self, data: int):
        """
        Write one byte to the I2C address.

        Args:
            data: The 8-bit value to write.
        """

        with SMBus(bus=self._i2c_bus) as smbus:
            smbus.write_byte(
                i2c_addr=self._i2c_address,
                value=data,
            )

