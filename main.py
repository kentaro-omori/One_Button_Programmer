#!/usr/bin/env python3
"""
main.py: Raspberry Pi Zero 2 W で ATtiny1616 に UPDI 経由で書き込むプログラム
"""

import os
import time
import subprocess
import glob
import RPi.GPIO as GPIO
import smbus

class LED:
    """GPIO ピン制御用の LED クラス"""

    def __init__(self, pin):
        """
        Args:
            pin (int): BCM モードの GPIO ピン番号
        """
        self.pin = pin
        GPIO.setup(self.pin, GPIO.OUT)
        GPIO.output(self.pin, GPIO.LOW)

    def on(self):
        """LED を点灯する"""
        GPIO.output(self.pin, GPIO.HIGH)

    def off(self):
        """LED を消灯する"""
        GPIO.output(self.pin, GPIO.LOW)


class Buzzer:
    """GPIO ピン制御用のブザー クラス"""

    def __init__(self, pin):
        """
        Args:
            pin (int): BCM モードの GPIO ピン番号
        """
        self.pin = pin
        GPIO.setup(self.pin, GPIO.OUT)
        GPIO.output(self.pin, GPIO.LOW)

    def buzz(self, duration_sec):
        """
        Args:
            duration_sec (float): 鳴動時間（秒）
        """
        # 440Hz の PWM でブザーを鳴動
        pwm = GPIO.PWM(self.pin, 440)
        pwm.start(50)  # デューティ比 50%
        time.sleep(duration_sec)
        pwm.stop()
        GPIO.output(self.pin, GPIO.LOW)


class Button:
    """GPIO ピン入力用のボタン クラス（簡易デバウンス付き）"""

    def __init__(self, pin, bounce_time=0.01):
        """
        Args:
            pin (int): BCM モードの GPIO ピン番号
            bounce_time (float): デバウンス時間（秒）
        """
        self.pin = pin
        self.bounce_time = bounce_time
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    def is_pressed(self):
        """
        Returns:
            bool: 押下検知時に True を返す
        """
        if GPIO.input(self.pin) == GPIO.HIGH:
            time.sleep(self.bounce_time)
            if GPIO.input(self.pin) == GPIO.HIGH:
                return True
        return False


class LCD:
    """I2C接続のLCDディスプレイクラス"""
    LCD_CONTROL_REGISTER = 0x00
    LCD_DATA_REGISTER = 0x40
    CMD_FUNCTIONSET = 0x38
    CMD_BIAS_OSC = 0x14
    CMD_CONTRAST_SET = 0x70
    CMD_POWER_ICON_CTRL = 0x5C
    CMD_FOLLOWER_CTRL = 0x6C
    CMD_DISPLAY_ON = 0x0C
    CMD_CLEAR = 0x01
    CMD_ENTRY_MODE = 0x06

    def __init__(self, address=0x3e, backlight_pin=None, busnum=1):
        """
        Args:
            address (int): I2Cアドレス
            backlight_pin (int): バックライト制御GPIOピン番号
            busnum (int): I2Cバス番号
        """
        self.address = address
        self.bus = smbus.SMBus(busnum)
        self.backlight_pin = backlight_pin
        if backlight_pin is not None:
            GPIO.setup(backlight_pin, GPIO.OUT)
            GPIO.output(backlight_pin, GPIO.HIGH)
        time.sleep(0.05)
        # 初期化シーケンス (AQM0802A / ST7032)
        # 拡張命令セットモード
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x39)
        time.sleep(0.005)
        # 内部発振周波数設定
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x14)
        time.sleep(0.005)
        # コントラスト設定下位4bit
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x70 | 0x0F)
        time.sleep(0.005)
        # コントラスト設定上位2bit + ブースタON
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x5C | 0x04)
        time.sleep(0.005)
        # フォロワー制御
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x6C)
        time.sleep(0.2)
        # 標準命令セットに戻す
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x38)
        time.sleep(0.005)
        # 表示オン, カーソルオフ
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x0C)
        time.sleep(0.005)
        # 表示クリア
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x01)
        time.sleep(0.002)
        # エントリモード設定
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, 0x06)
        time.sleep(0.005)

    def clear(self):
        """LCDの表示をクリアします."""
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, self.CMD_CLEAR)
        time.sleep(0.002)

    def display(self, text, line=0):
        """指定行にテキストを表示します."""
        addr = 0x80 + (0x40 * line)
        self.bus.write_byte_data(self.address, self.LCD_CONTROL_REGISTER, addr)
        for c in text.ljust(16)[:16]:
            self.bus.write_byte_data(self.address, self.LCD_DATA_REGISTER, ord(c))

    def backlight(self, on):
        """バックライトをオン/オフします."""
        if self.backlight_pin is not None:
            GPIO.output(self.backlight_pin, GPIO.HIGH if on else GPIO.LOW)


class Programmer:
    """pymcuprog で ATtiny1616 を UPDI 経由で書き込むクラス"""

    def write_hex(self, file_path):
        """
        Args:
            file_path (str): 書き込む .hex ファイルのパス
        Returns:
            bool: 成功時 True、失敗時 False
        """
        cmd = [
            "pymcuprog", "write",
            "-t", "uart",
            "-u", "/dev/ttyAMA0",
            "-d", "attiny1616",
            "-f", file_path,
            "--erase",
            "--verify",
        ]
        # デバッグ用: 実行コマンドを表示
        print(f"実行コマンド: {' '.join(cmd)}")
        # コマンド実行 (出力をキャプチャ)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print("プログラミングエラー:")
            if result.stdout:
                print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            return False
        return True


def main():
    # GPIO 初期化
    GPIO.setmode(GPIO.BCM)

    # ハードウェアオブジェクト生成
    green_led = LED(22)
    yellow_led = LED(27)
    buzzer = Buzzer(23)
    button = Button(24)
    programmer = Programmer()
    button2 = Button(21)
    lcd = LCD(address=0x3e, backlight_pin=26)

    # 起動時状態: 緑 LED 点灯
    green_led.on()
    yellow_led.off()

    # 初期hex選択
    base_dir = os.path.dirname(os.path.abspath(__file__))
    hex_dir = os.path.join(base_dir, "hex")
    os.makedirs(hex_dir, exist_ok=True)
    hex_files = sorted(glob.glob(os.path.join(hex_dir, "*.hex")))
    selected_idx = 0
    if hex_files:
        lcd.display(os.path.basename(hex_files[selected_idx]), line=0)
    else:
        lcd.display("No HEX files", line=0)

    try:
        while True:
            # hexファイル選択: スイッチ2押下で次を表示
            if button2.is_pressed():
                hex_files = sorted(glob.glob(os.path.join(hex_dir, "*.hex")))
                if hex_files:
                    selected_idx = (selected_idx + 1) % len(hex_files)
                    lcd.display(os.path.basename(hex_files[selected_idx]), line=0)
                time.sleep(0.2)

            if button.is_pressed():
                # 書込み開始
                green_led.off()
                yellow_led.on()

                # 選択中のhexファイルを書込
                if not hex_files:
                    print("No HEX files to program")
                else:
                    target = hex_files[selected_idx]
                    programmer.write_hex(target)

                # 書込み後処理
                yellow_led.off()
                buzzer.buzz(1.0)
                green_led.on()

            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
