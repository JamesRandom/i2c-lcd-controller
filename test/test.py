#!/usr/bin/env python3

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
lcd.display_on(False)
sleep(2)
lcd.backlight_on(False)
