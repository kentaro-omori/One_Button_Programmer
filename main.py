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
import signal

# イベント検出用フラグ
file_select_event = False

# SW2ボタンの長押し検出用変数
sw2_press_time = None
sw2_long_press_threshold = 3.0  # 長押しと判定する秒数
sw2_long_press_check = False  # 長押しチェック中かどうか

def on_file_select(channel):
    """ボタン2割り込みコールバック"""
    global file_select_event, sw2_press_time, sw2_long_press_check
    
    # ボタンの状態を確認
    if GPIO.input(channel) == (0 if button2.pull_up else 1):  # 押された状態
        # ボタン押下時刻を記録
        sw2_press_time = time.time()
        sw2_long_press_check = True
        print("SW2押下検出 - 長押しチェック開始")
    else:  # 解放された状態
        if sw2_press_time is not None:
            # 押していた時間を計算
            press_duration = time.time() - sw2_press_time
            sw2_press_time = None
            sw2_long_press_check = False
            
            # 長押しだった場合はシャットダウン処理
            if press_duration >= sw2_long_press_threshold:
                print(f"SW2長押し検出: {press_duration:.1f}秒")
                shutdown_system()
            else:
                # 短押しの場合は通常のファイル選択処理
                # 既に処理中の場合は無視（二重実行防止）
                if not file_select_event:
                    file_select_event = True
                    print(f"SW2短押し検出: {press_duration:.1f}秒")

# SW1(書き込みボタン)の割り込みフラグ
write_button_pressed = False

def on_write_button(channel):
    """ボタン1割り込みコールバック"""
    global write_button_pressed
    # 既に処理中の場合は無視（二重実行防止）
    if not write_button_pressed:
        write_button_pressed = True
        print("SW1割り込み検出")

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
    """GPIO ピン制御用のボタン クラス"""

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

    def is_active(self):
        """
        Returns:
            bool: ボタンがアクティブ状態（押されている）かどうか
        """
        return GPIO.input(self.pin) == self.active_level
        
    def is_pressed(self):
        """
        Returns:
            bool: 押下検知時に True を返す
        """
        if self.is_active():
            time.sleep(self.bounce_time)
            if self.is_active():
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
        # コントラスト設定下位4bit - 適切な値に設定 (0x04)
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x70 | 0x04])
        time.sleep(0.005)
        # コントラスト設定上位2bit + ブースタON - 中間値に設定 (0x01)
        self.bus.write_i2c_block_data(self.address, self.LCD_CONTROL_REGISTER, [0x5C | 0x01])
        time.sleep(0.005)
        # フォロワー制御 - 適切な電圧値に設定
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


def shutdown_system():
    """システムを安全にシャットダウンする"""
    try:
        # 全てのLEDを消灯する前に警告表示
        # 赤LEDを点滅させて警告
        for _ in range(5):
            GPIO.output(17, GPIO.HIGH)  # red LED on
            time.sleep(0.2)
            GPIO.output(17, GPIO.LOW)   # red LED off
            time.sleep(0.2)
            
        # LCDにシャットダウンメッセージを表示
        lcd = LCD(address=0x3e, backlight_pin=26)
        lcd.display("Shutdown", line=0)
        lcd.display("in progress", line=1)
        
        # 全てのLEDを消灯
        GPIO.output(22, GPIO.LOW)  # green LED
        GPIO.output(27, GPIO.LOW)  # yellow LED
        GPIO.output(17, GPIO.LOW)  # red LED
        
        print("\n*** システムをシャットダウンします ***")
        print("*** SW2ボタンの長押しによるシャットダウン ***")
        time.sleep(1)  # メッセージを表示する時間を確保
        
        # システムをシャットダウン
        subprocess.call(['sudo', 'shutdown', '-h', 'now'])
    except Exception as e:
        print(f"\n*** シャットダウン中にエラーが発生しました: {e} ***")

# 長押しチェック用の関数
def check_long_press():
    """長押し中かどうかをチェックし、長押しを検出したらシャットダウンする"""
    global sw2_press_time, sw2_long_press_check
    
    # 長押しチェック中で、時間が経過していればシャットダウン
    if sw2_long_press_check and sw2_press_time is not None:
        press_duration = time.time() - sw2_press_time
        if press_duration >= sw2_long_press_threshold:
            print(f"SW2長押し検出: {press_duration:.1f}秒")
            sw2_press_time = None
            sw2_long_press_check = False
            shutdown_system()

def main():
    global file_select_event
    global write_button_pressed
    # GPIO 初期化
    GPIO.setmode(GPIO.BCM)

    # ハードウェアオブジェクト生成
    green_led = LED(22)
    yellow_led = LED(27)
    buzzer = Buzzer(23)
    button = Button(24)
    programmer = Programmer()
    # SW2ボタンのチャタリング対策を強化するため、デバウンス時間を延長
    button2 = Button(21, bounce_time=0.3, pull_up=True)  # 0.01秒→0.3秒に変更
    lcd = LCD(address=0x3e, backlight_pin=26)
    red_led = LED(17)

    # 割り込み設定: SW2の押下と解放の両方を検出する
    # チャタリング対策としてbouncetimeを300msに設定
    GPIO.add_event_detect(button2.pin,
                         GPIO.BOTH,  # 両エッジを検出
                         callback=on_file_select,
                         bouncetime=300)  # 直接300msを指定

    # 割り込み設定: SW1(書き込みボタン)押下時にフラグ設定
    # bouncetimeを長めに設定して二重検出を防止
    GPIO.add_event_detect(button.pin,
                         GPIO.RISING if not button.pull_up else GPIO.FALLING,
                         callback=on_write_button,
                         bouncetime=300)  # 300ms

    # 起動時状態: 緑 LED 点灯
    green_led.on()
    yellow_led.off()
    red_led.off()

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
        # 二行表示: 1行目に選択ファイル, 2行目に次のファイル
        lcd.display(cur[:8].ljust(8), line=0)
        lcd.display(nxt[:8].ljust(8), line=1)
    else:
        lcd.display("No HEX files", line=0)

    try:
        while True:
            # SW2長押しチェック
            check_long_press()
            
            # hexファイル選択: SW2割り込みフラグで次を表示
            if file_select_event:
                file_select_event = False
                hex_files = sorted(glob.glob(os.path.join(hex_dir, "*.hex")))
                if hex_files:
                    names = [os.path.basename(f) for f in hex_files]
                    # 次のファイル選択
                    selected_idx = (selected_idx + 1) % len(names)
                    cur = names[selected_idx]
                    nxt = names[(selected_idx + 1) % len(names)]
                    # 表示更新
                    lcd.display(cur[:8].ljust(8), line=0)
                    lcd.display(nxt[:8].ljust(8), line=1)
                    # 長いファイル名はスクロール (イベント検出で中断)
                    # ボタン操作がない限り繰り返しスクロールする
                    scroll_interrupted = False
                    if len(cur) > 8:
                        # 繰り返しスクロール用の無限ループ
                        while not file_select_event and not write_button_pressed:
                            scroll_str = cur + " " * 8
                            scroll_len = len(scroll_str)
                            for i in range(scroll_len):
                                lcd.display(scroll_str[i:i+8], line=0)
                                lcd.display(nxt[:8].ljust(8), line=1)
                                # 短い間隔で割り込みチェック
                                for _ in range(6):  # 0.3秒を0.05秒×6回に分割
                                    time.sleep(0.05)
                                    # 長押しチェックも行う
                                    check_long_press()
                                    if file_select_event or write_button_pressed:
                                        break
                                if file_select_event or write_button_pressed:
                                    break
                            
                            # スクロール間の待機時間を最小限にし、ほぼ連続的にスクロールする
                            # 待機時間なしで次のスクロールを開始
                            if not file_select_event and not write_button_pressed:
                                # スクロール間の待機は必要最小限にする
                                # 割り込みチェックのために最小限の待機を入れる
                                time.sleep(0.01)
                                if file_select_event or write_button_pressed:
                                    break
                        
                        # スクロール中にファイル選択ボタンが押された場合、フラグを再設定して次のループで確実にファイル切り替えが行われるようにする
                        if file_select_event:
                            continue
            # 短い間隔で割り込みチェック
            time.sleep(0.05)

            if write_button_pressed:
                write_button_pressed = False
                # 書込み開始
                green_led.off()
                yellow_led.on()
                lcd.display("Writing", line=1)

                # 選択中のhexファイルを書込
                if not hex_files:
                    lcd.display("No HEX", line=1)
                else:
                    target = hex_files[selected_idx]
                    # 書込み実行と結果判定
                    success = False
                    try:
                        success = programmer.write_hex(target)
                    except Exception as e:
                        print("プログラミング例外:", e)
                    if success:
                        buzzer.buzz(1.0)
                        lcd.display("Finish!!", line=1)
                        red_led.off()
                        green_led.on()
                        # 短い間隔で割り込みチェック
                        for _ in range(20):  # 1秒を0.05秒×20回に分割
                            time.sleep(0.05)
                            if file_select_event:
                                file_select_event = False
                                break
                        # Finish後に元のファイル名表示に戻す
                        lcd.display(cur[:8].ljust(8), line=0)
                        lcd.display(nxt[:8].ljust(8), line=1)
                    else:
                        lcd.display("Error!!", line=1)
                        red_led.on()
                        # エラー時はスイッチ押下まで待機
                        while True:
                            if write_button_pressed or file_select_event:
                                red_led.off()
                                if file_select_event:
                                    file_select_event = False
                                if write_button_pressed:
                                    write_button_pressed = False
                                # ボタンが離されるのを待つ（短い間隔でチェック）
                                while button.is_active():
                                    time.sleep(0.05)
                                break
                            time.sleep(0.05)
                # 書込み後処理
                yellow_led.off()
                # 短い間隔で割り込みチェック
                for _ in range(20):  # 1秒を0.05秒×20回に分割
                    time.sleep(0.05)
                    if file_select_event:
                        break
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
