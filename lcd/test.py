
from time import sleep

from i2c_lcd import LCD

lcd = LCD()

lcd.clear_display()
lcd.move_to(0, 5)
lcd.print("Hello world")

# Right to left text
lcd.left_to_right(False)
lcd.print_at(2, 15, "Hello world")
lcd.left_to_right(True)

# Turn off display
sleep(5)
lcd.display(False)
lcd.backlight(False)
