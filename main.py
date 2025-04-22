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
import sys
import shutil

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

    def __init__(self, pin, bounce_time=0.01, pull_up=False):
        """
        Args:
            pin (int): BCM モードの GPIO ピン番号
            bounce_time (float): デバウンス時間（秒）
            pull_up (bool): プルアップ(True)またはプルダウン(False)設定
        """
        self.pin = pin
        self.bounce_time = bounce_time
        self.pull_up = pull_up
        pud = GPIO.PUD_UP if pull_up else GPIO.PUD_DOWN
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=pud)
        self.active_level = GPIO.LOW if pull_up else GPIO.HIGH

    def is_pressed(self):
        """
        Returns:
            bool: 押下検知時に True を返す
        """
        if GPIO.input(self.pin) == self.active_level:
            time.sleep(self.bounce_time)
            if GPIO.input(self.pin) == self.active_level:
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
        # 初期化シーケンス (AQM0802A / ST7032) - 拡張命令セットモード
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x39])
        time.sleep(0.005)
        # 内部発振周波数設定
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x14])
        time.sleep(0.005)
        # コントラスト設定下位4bit
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x70 | 0x0F])
        time.sleep(0.005)
        # コントラスト設定上位2bit + ブースタON
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x5C | 0x04])
        time.sleep(0.005)
        # フォロワー制御
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x6C])
        time.sleep(0.2)
        # 標準命令セットに戻す
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x38])
        time.sleep(0.005)
        # 表示オン, カーソルオフ
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x0C])
        time.sleep(0.005)
        # 表示クリア
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x01])
        time.sleep(0.002)
        # エントリモード設定
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x06])
        time.sleep(0.005)

    def clear(self):
        """LCDの表示をクリアします."""
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [self.CMD_CLEAR])
        time.sleep(0.002)

    def display(self, text, line=0):
        """指定行にテキストを表示します."""
        addr = 0x80 + (0x40 * line)
        # DDRAMアドレス設定
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [addr])
        # データ書込み
        for c in text.ljust(8)[:8]:
            self.bus.write_i2c_block_data(self.address, self.LCD_DATA_REGISTER, [ord(c)])

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
        # pymcuprog コマンドを検出
        script = shutil.which("pymcuprog")
        if not script:
            script = os.path.join(os.path.dirname(sys.executable), "pymcuprog")
        # 存在・実行権限チェック
        if not os.path.isfile(script) or not os.access(script, os.X_OK):
            print("Error: pymcuprog command not found. Please install and ensure it's in PATH.")
            return False
        # コマンド構築
        cmd = [script, "write", 
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
    button2 = Button(21, bounce_time=0.01, pull_up=True)
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
        names = [os.path.basename(f) for f in hex_files]
        cur = names[selected_idx]
        nxt = names[(selected_idx+1) % len(names)]
        # 二行表示: 1行目に選択ファイル (@付き), 2行目に次のファイル
        lcd.display(("@"+cur)[:8].ljust(8), line=0)
        lcd.display(nxt[:8].ljust(8), line=1)
    else:
        lcd.display("No HEX files", line=0)

    try:
        while True:
            # hexファイル選択: スイッチ2押下で次を表示
            if button2.is_pressed():
                hex_files = sorted(glob.glob(os.path.join(hex_dir, "*.hex")))
                if hex_files:
                    names = [os.path.basename(f) for f in hex_files]
                    selected_idx = (selected_idx + 1) % len(names)
                    cur = names[selected_idx]
                    nxt = names[(selected_idx+1) % len(names)]
                    # SW2押下後のリリース待機
                    while button2.is_pressed():
                        time.sleep(0.05)
                    # ファイル名スクロール表示 (1行目のみ), SW2押下で中断
                    scroll_str = "@" + cur + " " * 8
                    if len(cur) <= 8:
                        lcd.display(scroll_str[:8], line=0)
                        lcd.display(nxt[:8].ljust(8), line=1)
                    else:
                        stop_scroll = False
                        # SW2が押されるまで繰り返しスクロール
                        while not stop_scroll:
                            for i in range(len(scroll_str) - 7):
                                lcd.display(scroll_str[i:i+8], line=0)
                                lcd.display(nxt[:8].ljust(8), line=1)
                                # 0.3秒間を0.01秒刻みでSW2チェック
                                start = time.time()
                                while time.time() - start < 0.3:
                                    if button2.is_pressed():
                                        stop_scroll = True
                                        break
                                    time.sleep(0.01)
                                if stop_scroll:
                                    break
                        # 最終表示
                        lcd.display(scroll_str[:8], line=0)
                        lcd.display(nxt[:8].ljust(8), line=1)

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
