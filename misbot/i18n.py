"""Языки интерфейса и все строки, которые видит пользователь.

Строки лежат по ключам, а внутри ключа — по языкам: так обе версии одной фразы
стоят рядом, и при правке текста трудно забыть про перевод. Сборка сообщений
осталась в [[formatting]] — здесь только слова.

Чего здесь нет. Во-первых, контента с mis.ge: названия препаратов, аптек и
адреса приходят с сайта и переводятся словарями forms.py и landmarks.py, у
которых свои языковые слои. Для грузинского интерфейса они не переводятся вовсе
— сайт и так грузинский, и показывать оригинал правильнее любого транслита.
Во-вторых, служебных сообщений владельцу (/stats, алерты о поломке разбора): их
читает один человек, и переводить их незачем.

Незнакомый язык или дырка в переводе — не повод показать пустоту: `text()`
откатывается на русский.
"""

from __future__ import annotations

from typing import Dict, Tuple

RU = "ru"
KA = "ka"
EN = "en"

DEFAULT = RU

SUPPORTED: Tuple[str, ...] = (RU, KA, EN)
"""Языки, между которыми можно выбирать.

Кнопки строятся из этого кортежа, так что добавление языка — одна строчка плюс
переводы. Пока переводов нет, язык сюда не попадает: кнопка, ведущая на чужой
интерфейс, обманывала бы.
"""

NAMES: Dict[str, str] = {
    # Каждый язык назван на себе самом: так свой находят, не зная остальных.
    RU: "Русский",
    KA: "ქართული",
    EN: "English",
}


def text(key: str, lang: str) -> str:
    """Строка на нужном языке. Нет перевода — отдаём русский, но не пустоту."""
    translations = STRINGS[key]
    return translations.get(lang) or translations[DEFAULT]


def known(lang: str) -> bool:
    return lang in SUPPORTED


STRINGS: Dict[str, Dict[str, str]] = {
    # --- общее -------------------------------------------------------------
    "disclaimer": {
        RU: "Бот показывает цены и наличие. Он не назначает лечение и не заменяет врача.",
        KA: "ბოტი აჩვენებს ფასებსა და მარაგებს. ის არ ნიშნავს მკურნალობას "
            "და ექიმს ვერ ჩაანაცვლებს.",
        EN: "The bot shows prices and availability. It does not prescribe "
            "treatment and is no substitute for a doctor.",
    },
    "source": {
        RU: "Источник",
        KA: "წყარო",
        EN: "Source",
    },

    # --- выбор языка -------------------------------------------------------
    "choose_language": {
        # Экран видят до того, как язык выбран, поэтому заголовок повторён на
        # обоих языках: человек должен узнать свой, не зная чужого.
        RU: "Выберите язык / აირჩიეთ ენა",
        KA: "Выберите язык / აირჩიეთ ენა",
        EN: "Выберите язык / აირჩიეთ ენა / Choose a language",
    },
    "language_chosen": {
        RU: "Язык: <b>Русский</b>.",
        KA: "ენა: <b>ქართული</b>.",
        EN: "Language: <b>English</b>.",
    },

    # --- приветствие и справка ---------------------------------------------
    "greeting": {
        RU: "Привет! Я ищу лекарства по аптекам Грузии.\n\n"
            "Напишите название препарата — по-русски, латиницей или по-грузински, "
            "например <code>нурофен</code>. Я покажу, в каких аптеках он есть "
            "и сколько стоит.\n\n"
            "Город можно выбрать командой /city, язык — /language.",
        KA: "გამარჯობა! ვეძებ წამლებს საქართველოს აფთიაქებში.\n\n"
            "დაწერეთ პრეპარატის სახელი — ქართულად, ლათინურად ან რუსულად, "
            "მაგალითად <code>ნუროფენი</code>. გაჩვენებთ, რომელ აფთიაქებშია "
            "და რა ღირს.\n\n"
            "ქალაქს აირჩევთ ბრძანებით /city, ენას — /language.",
        EN: "Hi! I look up medicines in Georgian pharmacies.\n\n"
            "Send a medicine name — in English, Georgian or Russian, for "
            "example <code>nurofen</code>. I'll show which pharmacies have it "
            "and what it costs.\n\n"
            "Pick a city with /city, a language with /language.",
    },
    "help": {
        RU: "<b>Как пользоваться</b>\n\n"
            "Просто напишите название препарата: <code>нурофен</code>, "
            "<code>diclofenac</code>, <code>ნუროფენი</code>.\n\n"
            "Из списка выберите нужную форму выпуска — покажу аптеки с ценами.\n\n"
            "Под списком аптек есть кнопка «Следить»: я буду проверять препарат "
            "раз в сутки и напишу, когда он появится или подешевеет.\n\n"
            "<b>Команды</b>\n"
            "/city — выбрать город\n"
            "/language — выбрать язык\n"
            "/watching — за чем слежу\n"
            "/about — откуда данные",
        KA: "<b>როგორ ვისარგებლოთ</b>\n\n"
            "უბრალოდ დაწერეთ პრეპარატის სახელი: <code>ნუროფენი</code>, "
            "<code>diclofenac</code>, <code>нурофен</code>.\n\n"
            "სიიდან აირჩიეთ საჭირო ფორმა — გაჩვენებთ აფთიაქებს ფასებით.\n\n"
            "აფთიაქების სიის ქვეშ არის ღილაკი «თვალყურის დევნება»: დღეში ერთხელ "
            "შევამოწმებ და შეგატყობინებთ, როცა პრეპარატი გამოჩნდება ან გაიაფდება.\n\n"
            "<b>ბრძანებები</b>\n"
            "/city — ქალაქის არჩევა\n"
            "/language — ენის არჩევა\n"
            "/watching — რას ვადევნებ თვალყურს\n"
            "/about — საიდან არის მონაცემები",
        EN: "<b>How to use this</b>\n\n"
            "Just send a medicine name: <code>nurofen</code>, "
            "<code>diclofenac</code>, <code>ნუროფენი</code>.\n\n"
            "Choose the form you need from the list — I'll show pharmacies with "
            "prices.\n\n"
            "Under the pharmacy list there's a «Watch» button: I'll check the "
            "medicine once a day and tell you when it shows up or gets cheaper.\n\n"
            "<b>Commands</b>\n"
            "/city — choose a city\n"
            "/language — choose a language\n"
            "/watching — what I'm watching\n"
            "/about — where the data comes from",
    },
    "about": {
        RU: "Данные о наличии и ценах бот берёт с сайта "
            '<a href="{source_url}">mis.ge</a> — это открытый справочник аптек Грузии. '
            "Бот их не хранит и не перепродаёт, а только показывает.\n\n"
            "<b>Важно про даты.</b> Аптеки обновляют остатки сами и делают это "
            "по-разному: у части данные свежие, у части им больше года. "
            "Дату обновления я показываю у каждой строки — смотрите на неё "
            "и лучше позвоните в аптеку перед поездкой.\n\n"
            "<b>Приватность.</b> Тексты запросов не сохраняются. Бот считает обезличенную "
            "статистику — сколько было запросов и сколько из них нашлось; кто именно "
            "спрашивал, из неё не видно: telegram id не хранится, вместо него хеш. "
            "Учтите, что сайт-источник работает без шифрования, так что название "
            "препарата уходит к нему открытым текстом.\n\n"
            "Связь: {contact}",
        KA: "მარაგებისა და ფასების მონაცემებს ბოტი იღებს საიტიდან "
            '<a href="{source_url}">mis.ge</a> — ეს არის საქართველოს აფთიაქების '
            "ღია ცნობარი. ბოტი მათ არ ინახავს და არ ყიდის, მხოლოდ აჩვენებს.\n\n"
            "<b>მნიშვნელოვანია თარიღების შესახებ.</b> აფთიაქები მარაგებს თავად "
            "აახლებენ და სხვადასხვანაირად: ზოგთან მონაცემები ახალია, ზოგთან "
            "წელზე მეტის წინანდელი. განახლების თარიღს ყოველ სტრიქონთან ვაჩვენებ — "
            "მიაქციეთ ყურადღება და წასვლამდე სჯობს დაურეკოთ აფთიაქს.\n\n"
            "<b>კონფიდენციალურობა.</b> მოთხოვნების ტექსტები არ ინახება. ბოტი ითვლის "
            "უპიროვნო სტატისტიკას — რამდენი მოთხოვნა იყო და რამდენი მათგანი მოიძებნა; "
            "ვინ ეძებდა, აქედან არ ჩანს: telegram id არ ინახება, მის ნაცვლად — ჰეში. "
            "გაითვალისწინეთ, რომ საიტი-წყარო შიფრაციის გარეშე მუშაობს, ამიტომ "
            "პრეპარატის სახელი მას ღია ტექსტად მიდის.\n\n"
            "კონტაქტი: {contact}",
        EN: "Availability and prices come from <a "
            "href=\"{source_url}\">mis.ge</a> — an open directory of Georgian "
            "pharmacies. The bot neither stores nor resells that data, it only "
            "shows it.\n\n"
            "<b>About the dates.</b> Pharmacies update their stock themselves "
            "and do it unevenly: some data is fresh, some is over a year old. I "
            "show the update date on every line — look at it, and better call "
            "the pharmacy before going.\n\n"
            "<b>Privacy.</b> Your queries are not stored. The bot counts "
            "anonymous statistics — how many searches there were and how many "
            "found something; who asked is not visible: no telegram id is kept, "
            "only a hash. Note that the source site works without encryption, "
            "so the medicine name travels to it in plain text.\n\n"
            "Contact: {contact}",
    },

    # --- поиск -------------------------------------------------------------
    "searching": {
        RU: "Ищу «{query}»…",
        KA: "ვეძებ «{query}»…",
        EN: "Looking up «{query}»…",
    },
    "nothing_found": {
        # Международное название первым: сайт хранит названия латиницей, и это
        # не «ещё один совет», а самый действенный из трёх.
        RU: "По запросу «{query}» ничего не нашлось.\n\n"
            "Попробуйте международное название латиницей "
            "(<code>cetirizine</code>), действующее вещество вместо торговой "
            "марки (<code>ибупрофен</code> вместо <code>нурофен</code>) "
            "или просто первые несколько букв.",
        KA: "მოთხოვნაზე «{query}» ვერაფერი მოიძებნა.\n\n"
            "სცადეთ საერთაშორისო დასახელება ლათინურად "
            "(<code>cetirizine</code>), მოქმედი ნივთიერება სავაჭრო სახელის "
            "ნაცვლად (<code>იბუპროფენი</code> და არა <code>ნუროფენი</code>) "
            "ან უბრალოდ პირველი რამდენიმე ასო.",
        EN: "Nothing found for «{query}».\n\n"
            "Try the international name in Latin script "
            "(<code>cetirizine</code>), the active ingredient instead of the "
            "brand (<code>ibuprofen</code> instead of <code>nurofen</code>), or "
            "just the first few letters.",
    },
    "too_short": {
        RU: "Слишком короткий запрос — нужно хотя бы три буквы.",
        KA: "მოთხოვნა ძალიან მოკლეა — საჭიროა სულ მცირე სამი ასო.",
        EN: "That query is too short — at least three letters, please.",
    },
    "site_unavailable": {
        RU: "Сайт-источник сейчас не отвечает. Это бывает — попробуйте через "
            "несколько минут.",
        KA: "საიტი-წყარო ამჟამად არ პასუხობს. ასეც ხდება — სცადეთ რამდენიმე "
            "წუთში.",
        EN: "The source site isn't responding right now. It happens — try again "
            "in a few minutes.",
    },
    "site_blocked": {
        # Не «попробуйте через несколько минут»: блокировка сама не проходит,
        # и ложный совет только заставит человека дёргать бота впустую.
        RU: "Сайт-источник сейчас не пускает бота — похоже, ограничил доступ. "
            "Я уже знаю о проблеме, скоро разберёмся.",
        KA: "საიტი-წყარო ამჟამად არ უშვებს ბოტს — როგორც ჩანს, წვდომა შეზღუდა. "
            "პრობლემის შესახებ უკვე ვიცი, მალე გავარკვევთ.",
        EN: "The source site is turning the bot away — it seems to have "
            "restricted access. I already know about it, we'll sort it out.",
    },
    "parser_broken": {
        RU: "Не смог разобрать ответ сайта: похоже, там что-то поменяли. "
            "Я уже знаю о проблеме, скоро починим.",
        KA: "ვერ გავარჩიე საიტის პასუხი: როგორც ჩანს, იქ რაღაც შეიცვალა. "
            "პრობლემის შესახებ უკვე ვიცი, მალე გამოვასწორებთ.",
        EN: "I couldn't make sense of the site's answer: looks like something "
            "changed there. I already know about the problem, it'll be fixed "
            "soon.",
    },
    "busy": {
        RU: "Ещё ищу предыдущий запрос, секунду…",
        KA: "ჯერ კიდევ ვეძებ წინა მოთხოვნას, ერთი წამი…",
        EN: "Still working on your previous query, one moment…",
    },

    # --- список найденного -------------------------------------------------
    "found_total": {
        RU: "Нашлось: <b>{total}</b>.",
        KA: "მოიძებნა: <b>{total}</b>.",
        EN: "Found: <b>{total}</b>.",
    },
    "showing_city": {
        RU: "Показываю город: <b>{city}</b>.",
        KA: "ვაჩვენებ ქალაქს: <b>{city}</b>.",
        EN: "Showing city: <b>{city}</b>.",
    },
    "pick_number": {
        RU: "Выберите номер — покажу аптеки.",
        KA: "აირჩიეთ ნომერი — გაჩვენებთ აფთიაქებს.",
        EN: "Pick a number — I'll show the pharmacies.",
    },
    "prescription": {
        RU: "по рецепту",
        KA: "რეცეპტით",
        EN: "prescription only",
    },
    "in_stock_one": {
        RU: "есть в {count} аптеке",
        KA: "არის {count} აფთიაქში",
        EN: "in {count} pharmacy",
    },
    "in_stock_many": {
        RU: "есть в {count} аптеках",
        KA: "არის {count} აფთიაქში",
        EN: "in {count} pharmacies",
    },
    "out_of_stock": {
        RU: "нет в наличии",
        KA: "არ არის მარაგში",
        EN: "out of stock",
    },

    # --- аптеки ------------------------------------------------------------
    "no_stock_in_city": {
        RU: "В городе <b>{city}</b> этого препарата сейчас нет.\n\n"
            "Попробуйте выбрать другой город командой /city.",
        KA: "ქალაქში <b>{city}</b> ეს პრეპარატი ამჟამად არ არის.\n\n"
            "სცადეთ სხვა ქალაქის არჩევა ბრძანებით /city.",
        EN: "This medicine isn't available in <b>{city}</b> right now.\n\n"
            "Try another city with /city.",
    },
    "more_pharmacies": {
        RU: "…и ещё {count} аптек — показываю самые дешёвые.",
        KA: "…და კიდევ {count} აფთიაქი — ვაჩვენებ ყველაზე იაფებს.",
        EN: "…and {count} more pharmacies — showing the cheapest.",
    },
    "price_unknown": {
        RU: "цена не указана",
        KA: "ფასი მითითებული არ არის",
        EN: "price not listed",
    },
    "round_the_clock": {
        RU: "круглосуточно",
        KA: "24 საათი",
        EN: "24/7",
    },
    "updated": {
        RU: "обновлено {date}",
        KA: "განახლდა {date}",
        EN: "updated {date}",
    },
    "updated_unknown": {
        RU: "дата обновления неизвестна",
        KA: "განახლების თარიღი უცნობია",
        EN: "update date unknown",
    },

    # --- города и язык -----------------------------------------------------
    "city_chosen": {
        RU: "Город: <b>{city}</b>. Напишите название препарата.",
        KA: "ქალაქი: <b>{city}</b>. დაწერეთ პრეპარატის სახელი.",
        EN: "City: <b>{city}</b>. Send a medicine name.",
    },
    "choose_city": {
        RU: "Сейчас ищу в: <b>{city}</b>.\n\nВыберите город:",
        KA: "ამჟამად ვეძებ აქ: <b>{city}</b>.\n\nაირჩიეთ ქალაქი:",
        EN: "Currently searching in: <b>{city}</b>.\n\n"
            "Choose a city:",
    },
    "city_unknown": {
        RU: "Такого города не знаю",
        KA: "ასეთი ქალაქი არ ვიცი",
        EN: "I don't know that city",
    },
    "nothing_everywhere": {
        RU: "Поиск сразу по всей Грузии сайт-источник не отдаёт: по нему приходит "
            "пустой ответ, даже когда препарат в аптеках есть.\n\n"
            "Выберите город — в нём поиск работает:",
        KA: "მთელ საქართველოზე ერთბაშად ძებნას საიტი-წყარო არ იძლევა: მასზე "
            "ცარიელი პასუხი მოდის მაშინაც კი, როცა პრეპარატი აფთიაქებშია.\n\n"
            "აირჩიეთ ქალაქი — მასში ძებნა მუშაობს:",
        EN: "The source site won't search the whole of Georgia at once: it "
            "returns an empty answer even when the medicine is in stock.\n\n"
            "Choose a city — search works within one:",
    },

    # --- аналоги -----------------------------------------------------------
    "analogues_title": {
        RU: "🧬 Аналоги: то же действующее вещество, <b>{generic}</b>. "
            "Нашлось: <b>{total}</b>.",
        KA: "🧬 ანალოგები: იგივე მოქმედი ნივთიერება, <b>{generic}</b>. "
            "მოიძებნა: <b>{total}</b>.",
        EN: "🧬 Same ingredient: <b>{generic}</b>. Found: <b>{total}</b>.",
    },
    "no_analogues": {
        RU: "Других препаратов с тем же действующим веществом не нашлось.",
        KA: "იმავე მოქმედი ნივთიერების სხვა პრეპარატები ვერ მოიძებნა.",
        EN: "No other medicines with the same active ingredient were found.",
    },
    "analogues_unavailable": {
        RU: "Не смог получить список аналогов. Попробуйте ещё раз чуть позже.",
        KA: "ანალოგების სია ვერ მივიღე. სცადეთ ცოტა მოგვიანებით.",
        EN: "I couldn't get the list of alternatives. Please try again a bit "
            "later.",
    },

    # --- подписки ----------------------------------------------------------
    "unnamed_medicine": {
        RU: "препаратом",
        KA: "პრეპარატს",
        EN: "this medicine",
    },
    "unnamed_medicine_short": {
        RU: "препарат",
        KA: "პრეპარატი",
        EN: "medicine",
    },
    "watch_added": {
        RU: "Слежу за <b>{name}</b> в городе <b>{city}</b>.\n\n"
            "Проверяю раз в сутки и напишу, когда препарат появится или подешевеет. "
            "Список подписок — /watching.",
        KA: "თვალყურს ვადევნებ <b>{name}</b> ქალაქში <b>{city}</b>.\n\n"
            "დღეში ერთხელ ვამოწმებ და შეგატყობინებთ, როცა პრეპარატი გამოჩნდება "
            "ან გაიაფდება. გამოწერების სია — /watching.",
        EN: "Watching <b>{name}</b> in <b>{city}</b>.\n\n"
            "I'll check once a day and write when it shows up or gets cheaper. "
            "Your list — /watching.",
    },
    "watch_removed": {
        RU: "Больше не слежу. Список подписок — /watching.",
        KA: "აღარ ვადევნებ თვალყურს. გამოწერების სია — /watching.",
        EN: "Not watching any more. Your list — /watching.",
    },
    "watch_limit": {
        RU: "Уже слежу за {limit} препаратами — это предел. "
            "Отпишитесь от ненужного через /watching, и можно будет добавить новый.",
        KA: "უკვე {limit} პრეპარატს ვადევნებ თვალყურს — ეს ზღვარია. "
            "გააუქმეთ ზედმეტი /watching-ით და შეძლებთ ახლის დამატებას.",
        EN: "I'm already watching {limit} medicines — that's the limit. Drop "
            "one via /watching and you can add a new one.",
    },
    "watch_list_empty": {
        RU: "Пока ни за чем не слежу.\n\n"
            "Найдите препарат, откройте аптеки и нажмите «Следить» — "
            "я буду проверять раз в сутки и напишу, когда он появится или подешевеет.",
        KA: "ჯერჯერობით არაფერს ვადევნებ თვალყურს.\n\n"
            "იპოვეთ პრეპარატი, გახსენით აფთიაქები და დააჭირეთ «თვალყურის დევნება» — "
            "დღეში ერთხელ შევამოწმებ და შეგატყობინებთ, როცა გამოჩნდება ან გაიაფდება.",
        EN: "I'm not watching anything yet.\n\n"
            "Find a medicine, open its pharmacies and press «Watch» — I'll "
            "check once a day and write when it shows up or gets cheaper.",
    },
    "watch_list_title": {
        RU: "<b>Слежу за препаратами</b>",
        KA: "<b>ვადევნებ თვალყურს პრეპარატებს</b>",
        EN: "<b>Watching</b>",
    },
    "watch_list_hint": {
        RU: "Чтобы перестать следить, нажмите номер.",
        KA: "თვალყურის დევნების შესაწყვეტად დააჭირეთ ნომერს.",
        EN: "To stop watching, press the number.",
    },
    "watch_state_priced": {
        RU: "есть, от {price} ₾",
        KA: "არის, {price} ₾-დან",
        EN: "in stock, from {price} ₾",
    },
    "watch_state_available": {
        RU: "есть",
        KA: "არის",
        EN: "in stock",
    },
    "watch_news_cheaper": {
        RU: "💰 <b>Подешевел</b>",
        KA: "💰 <b>გაიაფდა</b>",
        EN: "💰 <b>Cheaper now</b>",
    },
    "watch_news_cheaper_prices": {
        RU: ": было от {old} ₾, стало от {new} ₾",
        KA: ": იყო {old} ₾-დან, გახდა {new} ₾-დან",
        EN: ": was from {old} ₾, now from {new} ₾",
    },
    "watch_news_appeared": {
        RU: "🔔 <b>Появился в продаже</b>",
        KA: "🔔 <b>გამოჩნდა გაყიდვაში</b>",
        EN: "🔔 <b>Back in stock</b>",
    },
    "watch_news_city": {
        RU: "Город: {city}",
        KA: "ქალაქი: {city}",
        EN: "City: {city}",
    },
    "watch_news_hint": {
        RU: "Отписаться или посмотреть список — /watching.",
        KA: "გასაუქმებლად ან სიის სანახავად — /watching.",
        EN: "To unsubscribe or see the list — /watching.",
    },

    # --- всплывающие подсказки ---------------------------------------------
    "toast_try_later": {
        RU: "Сейчас не получилось, попробуйте позже",
        KA: "ახლა ვერ გამოვიდა, სცადეთ მოგვიანებით",
        EN: "Didn't work just now, try later",
    },
    "toast_watching": {
        RU: "Слежу",
        KA: "თვალყურს ვადევნებ",
        EN: "Watching",
    },
    "toast_unwatched": {
        RU: "Больше не слежу",
        KA: "აღარ ვადევნებ",
        EN: "Not watching any more",
    },

    # --- кнопки ------------------------------------------------------------
    "button_back": {
        RU: "← назад",
        KA: "← უკან",
        EN: "← back",
    },
    "button_more": {
        RU: "ещё →",
        KA: "კიდევ →",
        EN: "more →",
    },
    "button_watch": {
        RU: "🔔 Следить за препаратом",
        KA: "🔔 თვალყური ადევნე პრეპარატს",
        EN: "🔔 Watch this medicine",
    },
    "button_analogues": {
        RU: "🧬 Тот же состав",
        KA: "🧬 იგივე შემადგენლობა",
        EN: "🧬 Same ingredient",
    },

    # --- служебное ---------------------------------------------------------
    "chat_id": {
        RU: "Ваш telegram id: <code>{value}</code>\n\n"
            "Положите его в <code>MISGE_ADMIN_ID</code>, чтобы получать /stats "
            "и сообщения о поломке разбора.",
        KA: "თქვენი telegram id: <code>{value}</code>\n\n"
            "ჩაწერეთ იგი <code>MISGE_ADMIN_ID</code>-ში, რომ მიიღოთ /stats "
            "და შეტყობინებები გარჩევის შეფერხების შესახებ.",
        EN: "Your telegram id: <code>{value}</code>\n\n"
            "Put it in <code>MISGE_ADMIN_ID</code> to receive /stats and parser "
            "breakage alerts.",
    },
}
