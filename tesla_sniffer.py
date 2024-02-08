from splinter import Browser
from selenium import webdriver

from urllib.parse import parse_qs, urlencode
from time import sleep, time
from datetime import datetime
from subprocess import check_call
from requests import post as requests_post
from dataclasses import dataclass
from re import compile as re_compile
from bs4 import BeautifulSoup as bs
from json import loads as json_loads, dumps as json_dumps
from gettext import translation as gettext_translation
from babel.numbers import format_number

from PythonColorConsole import color_console
from pathlib import Path
import concurrent.futures
from os import cpu_count, name as os_name
from functools import cache as memoize

from geopy_utils import get_addr, get_distance, get_coords


CONFIGURATION = dict()
NOTIFIED = set()
SMSED = set()

CAR_ID_RE = re_compile("^(\d{3}_[0-9a-fA-f]{32})-.*$")
BASE_PRICE_RE = re_compile(r"^Prix de base: (\d+)$")
DISCOUNT_RE = re_compile(r"^.* tarifaire: (-\d+)$")


@memoize
def get_search_url():
    options = {
        "arrangeby": "plh",
        "zip": CONFIGURATION["zip"],
        "range": 0,
    }
    options.update(CONFIGURATION["car_options"])
    base_url = f'https://www.tesla.com/{CONFIGURATION["location_code"]}/inventory/{CONFIGURATION["car_status"]}/{CONFIGURATION["car_type"]}'
    url = base_url + "?" + urlencode(options)
    print(_("Search url:"), url)
    return url


@memoize
def get_car_url():
    options = {
        "postal": CONFIGURATION["zip"],
        "range": 0,
        "region": CONFIGURATION["region"],
        "coord": f'{CONFIGURATION["coords"][0]},{CONFIGURATION["coords"][1]}',
        "titleStatus": CONFIGURATION["car_status"],
        "redirect": "no",
    }
    base_url = f'https://www.tesla.com/{CONFIGURATION["location_code"]}/{CONFIGURATION["car_type"]}/order/XP7Y{{0}}'
    url = base_url + "?" + urlencode(options)
    print(_("Car url:"), url)
    return url


@memoize
def format_price(price: int, tokens_tr) -> str:
    return tokens_tr.gettext("${}").format(format_number(price))


@dataclass
class Car:
    price: int
    color: str
    description: str
    tow_hitch: bool = False
    base_price: int = 0
    discount: int = 0
    wheels: str = "?"
    origin: str = "?"
    car_id: str = ""
    locations: dict = None
    status: str = ""
    odometer: int = 99999
    tokens_tr: any = None

    @classmethod
    @memoize
    def read_bs4_card(cls, car_card, tokens_tr):
        def simplify_text(text):
            return text.replace("\xa0", "").replace("€", "").replace("\u200b", "").replace("\u202f", "").replace("&nbsp;", "").replace("$", "").replace(",", "")

        def read_price(text):
            return int(simplify_text(text))

        car_id = "?"
        if m := CAR_ID_RE.match(car_card["data-id"]):
            car_id = m.group(1)
        title = car_card.find_all('div', class_="tds-text_color--10")[0].get_text()
        price = car_card.find_all('span', class_="result-purchase-price tds-text--h4")[0].get_text().replace("\xa0€", "")
        try:
            price = read_price(price)
        except Exception as e:
            print(e)
            print(_("While handling conversion of: '{}'").format(price))
            return None

        origin = "?"
        status = "New"
        odometer = 99999
        locations = dict()
        if price <= CONFIGURATION["display_limit"]:
            html = ""
            while len(html) <= 10000:
                html = str(get_html_content(get_car_url().format(car_id)))
            for line in html.splitlines():
                if "tslaObj = " in line:
                    content = line.split(" = ", 1)[-1].rsplit(";", 1)[0]
                    try:
                        tesla_obj = json_loads(content)
                    except Exception:
                        break
                    Path(f"car_cards/{car_id}.json").write_text(json_dumps(tesla_obj, indent=2))
                    origin = tesla_obj["vin"][:3]
                    status = tesla_obj.get("product", dict()).get("data", dict()).get("TitleStatus", "???")
                    odometer = tesla_obj.get("product", dict()).get("data", dict()).get("Odometer", 0)
                    tesla_locations = tesla_obj.get("product", dict()).get("data", dict()).get("ComboVrlData", dict())
                    for tesla_loc_id in tesla_locations:
                        if not tesla_locations[tesla_loc_id].get("IsAtLocation", False):
                            continue
                        loc_coords = eval(f'({tesla_locations[tesla_loc_id]["Geolocation"]})')
                        try:
                            distance = get_distance(tuple(CONFIGURATION["coords"]), loc_coords)
                        except Exception as e:
                            print(e)
                            distance = 9999
                        try:
                            tmp = get_addr(loc_coords)
                            location = f"{tmp[0]} ({tmp[1]})"
                        except Exception as e:
                            print(_("Error getting addr for {}: {}").format(loc_coords, e))
                            location = str(loc_coords)
                        while distance in locations:
                            distance += 1
                        locations[distance] = location
                    #print(car_id, tesla_obj.get("product", dict()).get("data", dict()).get("ComboVrlData", dict()).get("58598", dict()).get("IsAtLocation", False))
                    break

        color = "???"
        wheels = "???"
        tow_hitch = False
        for i in car_card.find_all("li", class_="tds-list-item tds-text--caption"):
            text = i.get_text()
            if tokens_tr.gettext(" Paint") in text:
                color = text[8:]
            if tokens_tr.gettext(" Wheels") in text:
                wheels = text[7:]
            if i.get_text() == tokens_tr.gettext("Tow Hitch"):
                tow_hitch = True

        base_price = 0
        discount = 0
        captions = car_card.find_all('div', class_="tds-text--caption")
        for caption in captions:
            price_texts = caption.find_all("div", class_="tds-text--medium")
            for price_text in price_texts:
                text = simplify_text(price_text.get_text())
                if m := BASE_PRICE_RE.match(text):
                    base_price = int(m.group(1))
                if m := DISCOUNT_RE.match(text):
                    discount = int(m.group(1))
            if base_price == 0:
                base_price = price

        return cls(price, color, title, tow_hitch, base_price, discount, wheels, origin, car_id, locations, status, odometer, tokens_tr)

    def closest_distance(self):
        try:
            return min(self.locations)
        except ValueError:
            return 99999

    def closest_location(self):
        try:
            return self.locations[self.closest_distance()]
        except KeyError:
            return _("far far away (Naboo)")

    def is_worth_display(self):
        return self.price < CONFIGURATION["display_limit"]

    def is_worth_notification(self):
        return self.price < CONFIGURATION["notification_limit"]

    def notification_text(self):
        if self.tow_hitch:
            tow_hitch = "\n" + _("Tow Hitch")
        else:
            tow_hitch = ""
        title = f"{self.description}{tow_hitch}"
        content = f"{self.color}\n{self.price} ({self.discount})\n{self.car_id}"
        return (title, content)

    def is_worth_sms(self):
        return self.price < CONFIGURATION["sms_limit"]

    def sms_text(self):
        return f"{self.price} ({self.discount})\n{self.color}\n{self.description.split(',')[0]}"

    def __hash__(self):
        return hash(self.car_id)

    def __eq__(self, other):
        return self.car_id == other.car_id

    def __str__(self):
        result = f"{format_price(self.price, self.tokens_tr)} ({format_price(self.discount, self.tokens_tr)}): {self.description} [{self.origin}] {self.status}"
        if self.odometer > 50:
            result += f" ({self.odometer}km)"
        if self.tow_hitch:
            result += _(" --tow hitch-- ")
        result += f"\n        {self.color}/{self.wheels}"
        result += f"\n        {self.car_id}"
        found_one = False
        if CONFIGURATION["range"] > 0:
            for d in sorted(self.locations.keys()):
                if d <= CONFIGURATION["range"]:
                    result += f"\n        {d}km @ {self.locations[d]}"
                    found_one = True
        if not found_one:
            result += "\n        " + _("Closest:")
            result += f"\n        {self.closest_distance()}km @ {self.closest_location()}"
        return result


def notify(car: Car):
    print(_("Send Notification"))
    if os_name == "posix":
        check_call([
            "notify-send",
            "--app-name", "tesla-sniffer",
            *car.notification_text(),
            "-u",
            ("low", "normal")[car.is_worth_sms()],
            "-t",
            "1500",
            "-i",
            str(Path(__file__).parent / "tesla.png")
        ])
    else:
        # TODO: look at this: https://pypi.org/project/Windows-Toasts/
        print(_("No yet implemented"))


def send_sms(cc, car: Car):
    if CONFIGURATION["use_free_sms"]:
        send_sms_free(cc, car)
    else:
        cc.red()
        cc.bold()
        print(_("No SMS mechanism set"))
        cc.reset()


def send_sms_free(cc, car: Car):
    url = "https://smsapi.free-mobile.fr/sendmsg"
    object = {
        "user": CONFIGURATION["free_user"],
        "pass": CONFIGURATION["free_token"],
        "msg": car.sms_text()[0:100],
    }

    cc.cyan()
    print(_("Sending SMS: {}").format(object['msg']))
    cc.reset()
    try:
        res = requests_post(url, json=object, timeout=60)
        if res.status_code == 200:
            return True
    except Exception as e:
        print(_("Exception occurred"))
        res = repr(e)
    cc.red()
    print(_("SMS send failed!"))
    print(res)
    cc.reset()
    return False


def handle_notifications(cc, car: Car):
    global SMSED, NOTIFIED
    if car.is_worth_sms():
        cc.red()
    elif car.is_worth_notification():
        cc.yellow()
    else:
        cc.green()
    if car.is_worth_display():
        print(car)
    else:
        print(".", end="\r")
    cc.reset()
    if car.is_worth_notification():
        if car not in NOTIFIED:
            notify(car)
        NOTIFIED.add(car)
    if car.is_worth_sms():
        if car not in SMSED:
            send_sms(cc, car)
        SMSED.add(car)


def handle_mega_menu(browser):
    buttons = browser.find_by_css('button[id="dx-nav-item--Europe"]')
    if buttons and buttons[0].visible:
            buttons[0].mouse_over()
            buttons[0].click()
    fr_buttons = browser.find_by_css('a[lang="fr-FR"]')
    if fr_buttons and fr_buttons[0].visible:
        fr_buttons[0].mouse_over()
        fr_buttons[0].click()


def get_html_content(url):
    browser = get_spinter_browser()

    # Ensure filters are well taken into account afterwards
    browser.visit(url)
    soup = bs(browser.html, "lxml")

    try:
        browser.windows[0].close()
    except Exception:
        pass
    finally:
        del browser

    return soup


def prompt_settings_to_user(cc: color_console.ColorConsole, config_file: Path):
    cc.bold()
    print(_('Nothing configured yet. This script will create a configuration for you.'))
    print(_("To be able to do it, simply copy paste here the URL of the inventory search you want on Tesla website (including your required options)."))
    cc.reset()
    cc.yellow()
    print(_('For instance, for a Gray Model Y with 19" Wheels for Zip code 12345:'))
    print(_('https://www.tesla.com/inventory/new/my?PAINT=GRAY&WHEELS=NINETEEN&arrangeby=plh&zip=12345&range=0'))
    cc.reset()
    url_re = re_compile(r"https://(?:|www\.)tesla.com/(|[^/]+/)inventory/([^/]+)/([^\?]+)\?(.*)")
    match = None
    while match is None:
        url = input()
        match = url_re.match(url)

    url_params = parse_qs(match.group(4))
    car_options = {
        x: url_params[x][0]
        for x in url_params
        if x not in ("zip", "range", "arrangeby")
    }

    if "zip" not in url_params:
        print(_("Error: zip is not provided in URL: cannot continue."))
        return False

    def get_value(title, default):
        value = default
        cc.bold()
        cc.cyan()
        print(f"{title} [{value}]", end="")
        cc.reset()
        user_val = input()
        if user_val != "":
            # user entered a new value
            try:
                value = int(user_val)
            except ValueError:
                print(_("Error: hit [enter] or give a new numeric value."))
                value = default
            return get_value(title, value)
        # else: user validated the value
        return value

    if match.group(1):
        location = match.group(1)[:-1]  # remove last /
    else:
        location = "en_US"
    # Default settings:
    settings = {
        'zip': url_params["zip"][0],
        'location_code': location,
        'region': location[-2:],
        'coords': get_coords(location[-2:], url_params["zip"][0]),

        'car_status': match.group(2),
        'car_type': match.group(3),
        'car_options': car_options,

        'frequency': get_value(_("Update frequency (seconds)"), 120),
        'range': get_value(_("Display car not farer than (km)"), 300),

        'display_limit': get_value(_("Display cars cheaper than"), 43000),
        'notification_limit': get_value(_("Notify cheaper cars than"), 40000),

        'sms_limit': get_value(_("Send a SMS for cars cheaper than"), 38000),
        'use_free_sms': False,
        'free_user': "",
        'free_token': "",
    }

    content = json_dumps(settings, indent=2)
    return config_file.write_text(content) == len(content)


def read_config(cc: color_console.ColorConsole, config_file: Path):
    if not config_file.exists():
        return False
    content = config_file.read_text()
    try:
        configuration = json_loads(content)
    except Exception:
        return None
    return configuration


def get_spinter_browser():
    options = webdriver.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--headless')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-gpu')
    options.add_argument(f'user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.50 Safari/537.36')
    return Browser("chrome", options=options)


def main():
    global SMSED, NOTIFIED, CONFIGURATION

    # TODO: make it overridable by CLI option?
    #os_lang = gettext_translation('messages', "./locale", languages=[options.language])
    os_lang = gettext_translation('messages', "./locale")
    os_lang.install()

    cc = color_console.ColorConsole()
    config_file = Path("config.json")
    if \
        (not config_file.exists()) \
        and \
        (not prompt_settings_to_user(cc, config_file)) \
    :
        return 1
    CONFIGURATION = read_config(cc, config_file)
    if not CONFIGURATION:
        return 2
    freq = CONFIGURATION["frequency"]
    tokens_tr = gettext_translation('messages', "./locale", languages=[CONFIGURATION["location_code"]])

    Path("car_cards").mkdir(exist_ok=True)

    handle_history = True

    browser = get_spinter_browser()

    # Ensure filters are well taken into account afterwards
    browser.visit(get_search_url())
    handle_mega_menu(browser)

    if handle_history:
        history_file = Path("./history.csv")
        if not history_file.exists():
            history_file.write_text("date/time;number of cars;price;color;descr\n")

    while True:
        start_time = time()

        cars = set()
        while True:  # Prevent connection issues
            browser.visit(get_search_url())
            handle_mega_menu(browser)
            if len(str(browser.html)) > 1000:
                break
        soup = bs(browser.html, "lxml")
        minimum = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(cpu_count()//2, 16))) as executor:
            future_to_cars = [
                executor.submit(Car.read_bs4_card, car_card, tokens_tr)
                for car_card in soup.find_all("article", class_="result card")
            ]
            done_count = 0
            while done_count != len(future_to_cars):
                sleep(1)
                done_count = 0
                for item in future_to_cars:
                    if item.done():
                        done_count += 1
                print("\r" + _("Processed {}/{} car(s)...").format(done_count, len(future_to_cars)), end="")
            print("\r " + _("Processed {} cars!").format(len(future_to_cars)) + "                  ")
            for future in sorted(future_to_cars, key=lambda x: f"{x.result().price}{x.result().car_id}"):
                car = future.result()
                if car is None:
                    continue
                handle_notifications(cc, car)
                if minimum is None or minimum.price > car.price:
                    minimum = car
                cars.add(car)
        print(_("Handled {} cars in {:.2f}s").format(len(cars), time() - start_time), end=" ")
        try:
            print(f"(>={format_price(minimum.price, tokens_tr)})")
        except Exception:
            print("(???)")

        if handle_history and minimum is not None:
            history_content = history_file.read_text()
            history_content += f"{datetime.now()};{len(cars)};{minimum.price};{minimum.color};{minimum.description}\n"
            history_file.write_text(history_content)
        SMSED.intersection_update(cars)
        NOTIFIED.intersection_update(cars)
        cc.bold()
        print(f"[{datetime.now()}] - Wait {freq / 60:.1f} minutes")
        cc.reset()
        try:
            sleep(freq)
        except KeyboardInterrupt:
            break
        cc.magenta()
        print("-="*40)
        cc.reset()

    # This should be used to close session...
    try:
        browser.windows[0].close()
    except Exception:
        pass
    finally:
        del browser


if __name__ == "__main__":
    exit(main())
