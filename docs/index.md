# LCD Display Controller Reference

[Source code](https://github.com/JamesRandom/i2c-lcd-controller)

## Example

```{python}
from i2c_cd import LCD

lcd = LCD()

lcd.clear_display()
lcd.move_to(0, 5)
lcd.print("Hello world")
lcd.left_to_right(False)
lcd.print_at(2, 15, "Hello world")
```

## API

::: lcd.i2c_lcd.LCD
    options:
      show_source: false
