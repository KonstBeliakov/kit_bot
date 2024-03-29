import os.path
import threading

from google.oauth2 import service_account

from datetime import date
from time import sleep

import telebot
from telebot import types

from google_sheets_utils import *

TELEGRAM_KEY = os.getenv('TELEGRAM_KEY')
API_KEY = os.getenv('API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, 'credentials.json')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=credentials)
write_sheet = service.spreadsheets()

values = [[], [], []]


def values_get(x):
    global values
    t = [KIDS_SHEET_NAME, USERS_SHEET_NAME, TEACHER_SHEET_NAME]
    values[x] = read_from_table(API_KEY, SPREADSHEET_ID, f'{t[x]}!A1:AO1000')


def read_tables():
    global classes, kids, students, subjects, nicks, values
    global KIDS_SHEET_NAME, USERS_SHEET_NAME, TEACHER_SHEET_NAME, REVIEWS_SHEET_NAME

    settings = read_from_table(API_KEY, SPREADSHEET_ID, 'settings!A1:D1000')
    settings_dict = {i[0]: i[1] for i in settings}

    # read the table names from the settings table

    KIDS_SHEET_NAME = settings_dict['KIDS_SHEET_NAME']
    USERS_SHEET_NAME = settings_dict['USERS_SHEET_NAME']
    TEACHER_SHEET_NAME = settings_dict['TEACHER_SHEET_NAME']
    REVIEWS_SHEET_NAME = settings_dict['REVIEWS_SHEET_NAME']

    t = [threading.Thread(target=values_get, args=(i,)) for i in range(3)]

    for i in t:
        i.start()

    for i in t:
        i.join()

    classes = {}  # dictionary matching classes with lists of students in them
    for i, j in enumerate(values[0][0]):
        classes[j] = [values[0][k][i] for k in range(1, len(values[0])) if len(values[0][k]) > i and values[0][k][i]]

    kids = {j for i in classes.values() for j in i}

    students = {}  # dictionary matching students' names with a list of classes they belong to
    for cl, st in classes.items():
        for i in st:
            students[i] = students.get(i, []) + [cl]

    nick_index = values[1][0].index('nick')
    name_index = values[1][0].index('name')

    nicks = {}  # dictionary matching telegram nicknames to names

    for i in range(1, len(values[1])):
        if len(values[1][i]) > nick_index:
            nicks[values[1][i][nick_index]] = '' if len(values[1][i]) <= name_index else values[1][i][name_index]

    for student in students.keys():
        nicks[student] = student

    subjects = {}  # a dictionary matching classes with lists of subjects for them
    for i in range(1, len(values[2])):
        if len(values[2][i]) > 2:
            subjects[values[2][i][2]] = subjects.get(values[2][i][2], []) + [values[2][i][0]]


read_tables()

bot = telebot.TeleBot(TELEGRAM_KEY)

access_mode = {}

print('Бот успешно запущен')


def update():
    while True:
        sleep(60)
        print('updating data...', end='')
        read_tables()
        print('done')


update_tables = threading.Thread(target=update)

update_tables.start()


@bot.message_handler()
def get_user_text(message):
    global access_mode
    try:
        if message.from_user.username in access_mode:
            nick = message.from_user.username
            if access_mode[nick][1]:
                t = read_from_table(API_KEY, SPREADSHEET_ID, f'{REVIEWS_SHEET_NAME}!A1:D1000')

                user = str(nick) if access_mode[nick][1] == 'review' else None
                subject = access_mode[nick][0]

                write_to_table(write_sheet, SPREADSHEET_ID, f'{REVIEWS_SHEET_NAME}!A{len(t) + 1}:D{len(t) + 1}',
                               [[str(date.today()), subject, nicks.get(user, None), message.text]])

                del access_mode[nick]

                bot.send_message(message.chat.id, 'Спасибо за отзыв!')
            else:
                bot.send_message(message.chat.id, 'Перед тем как писать отзыв, пожалуйста выбери тип отзыва (обычный '
                                                  'или анонимный)')
        else:
            if message.from_user.username in nicks:
                nick = message.from_user.username
                name = nicks[nick]
                if name in students:
                    button_texts = set()
                    for cl in students[name]:
                        button_texts.update(subjects[cl])

                    markup = types.InlineKeyboardMarkup(row_width=2)
                    for button_text in button_texts:
                        markup.add(types.InlineKeyboardButton(button_text, callback_data=button_text))

                    bot.send_message(message.chat.id, 'Выбери к какому уроку ты хочешь написать отзыв:',
                                     reply_markup=markup)
                else:
                    bot.send_message(message.chat.id, f'Ошибка: ученик {name} не входит ни в один из классов.')
            else:
                bot.send_message(message.chat.id, f'Ошибка: Имя {message.from_user.username} не найдено в таблице.')
    except Exception as err:
        bot.send_message(message.chat.id, f'Ошибка: {err}')


@bot.callback_query_handler(func=lambda call: True)
def answer(call):
    global access_mode
    print('answer function was called')
    print(f'access_mode: {access_mode}')
    if call.data not in ['review', 'anonimous_review']:
        access_mode[call.from_user.username] = [call.data, None]

        markup = types.InlineKeyboardMarkup(row_width=2)

        markup.add(types.InlineKeyboardButton(text='Обычный отзыв', callback_data='review'),
                   types.InlineKeyboardButton(text='Анонимный отзыв', callback_data='anonimous_review'))

        bot.send_message(call.message.chat.id, f'Выбери какой тип отзыва ты хочешь оставить для урока {call.data}:',
                         reply_markup=markup)
    else:
        try:
            access_mode[call.from_user.username][1] = call.data
        except:
            bot.send_message(call.message.chat.id, 'Ошибка: урок к которому вы хотите оставить отзыв не найден.')
        else:
            bot.send_message(call.message.chat.id,
                             f'Теперь ты можешь написать отзыв к уроку {access_mode[call.from_user.username][0]}')


bot.polling(none_stop=True)
