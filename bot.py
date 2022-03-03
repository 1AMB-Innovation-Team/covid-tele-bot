# TOKEN:5249938330:AAF4vd0RX2Jdx_24vxDz3lSSWPUSWOOLRic
# TOKEN = '5249938330:AAF4vd0RX2Jdx_24vxDz3lSSWPUSWOOLRic'

#!/usr/bin/env python
# pylint: disable=C0116,W0613
# This program is dedicated to the public domain under the CC0 license.

'''
Send /start to initiate the conversation.
Press Ctrl-C on the command line to stop the bot.
'''
import logging
import datetime, dateparser
import html
import json
import traceback
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    CallbackContext,
    MessageHandler,
    Filters,
    PicklePersistence,
)
from postgrespersistence import PostgresPersistence
import re
import os
import psycopg2

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)


logger = logging.getLogger(__name__)

# Stages
# FIRST, SECOND = range(2)
TYPE, NAME, DATE = range(3)
# Callback data
# ONE, TWO, THREE, FOUR = range(4)
CP, AP, HR, CC = range(4)
NM, MC = range(2)
# dict keys
CPos, APos, Hrn, CCon = 'c','a','h','k'
ct = [CPos, APos, Hrn, CCon]
type_text = [
    'C+ on ',
    'HA Ag+ on ',
    'HRW/HRN on ',
    'KC on '
]
# Dictionary to store all cases
Cases = {
    CPos:{},
    APos:{},
    Hrn:{},
    CCon:{},
}
# List resend interval
resend_interval = datetime.timedelta(hours = 47)
# Unit Name
unit_name = '12FMD'

# for error logging
DEVELOPER_CHAT_ID = 291603849

PORT = int(os.environ.get('PORT', 5000))

def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

def start(update: Update, context: CallbackContext) -> None:
    '''Send message on `/start`.'''
    # Get user that sent /start and log his name
    user = update.message.from_user
    logger.info('User %s started the conversation.', user.first_name)
    
    logger.info('context: %s', context)
    chat_id = update.message.chat_id
    # load current case list from persistence store
    if('Cases' not in context.chat_data):
        context.chat_data['Cases'] = Cases
    c = context.chat_data['Cases']
    context.chat_data['cid'] = chat_id
    context.chat_data['unit'] = unit_name
    active_list_id = update.message.reply_text(
        generate_msg_text(c, context)
    ).message_id
    context.chat_data['ACTIVE'] = active_list_id
    logger.info('Active message id: %s', context.chat_data['ACTIVE'] )
    # list renewal scheduling
    remove_job_if_exists(str(chat_id), context)
    context.job_queue.run_once(sendlist, resend_interval, context=context, name=str(chat_id))
    return

def sl(update: Update, context: CallbackContext) -> None:
    if('cid' not in context.chat_data):
        chat_id = update.message.chat_id
        context.chat_data['cid'] = chat_id
        update.message.reply_text(
            f'Please use /start to begin tracking'
        )
        return
    # helper because i didnt want to overload
    sendlist(context)
    return
    
def sendlist(context: CallbackContext) -> None:
    '''Send message on `/list`.'''
    job = context.job
    if(job is not None):
        context = job.context
    logger.info('new list requested')
    if('Cases' not in context.chat_data):
        context.chat_data['Cases'] = Cases
    c = context.chat_data['Cases']
    bot = context.bot
    chat_id = context.chat_data['cid']
    active_list_id = bot.send_message(
        text=generate_msg_text(c, context),
        chat_id = chat_id
    ).message_id
    d = False
    if('d' in context.chat_data):
        d=context.chat_data['d']
    if(d):
        bot.delete_message(chat_id=chat_id, message_id=context.chat_data['ACTIVE'])
    context.chat_data['ACTIVE']= active_list_id
    # list renewal scheduling
    remove_job_if_exists(str(chat_id), context)
    context.job_queue.run_once(sendlist, resend_interval, context=context, name=str(chat_id))
    return


def help(update: Update, context: CallbackContext) -> None:
    '''Send message on `/help`.'''
    # Get user that sent /help and log his name
    user = update.message.from_user
    logger.info('User %s requested help.', user.first_name)
    update.message.reply_text(
        f'12FMD COVID CASE TRACKER\n'
        f'Use /add to add a case and /remove to remove.\n'
        f'Use /cancel to cancel an action midway.\n'
        f'Use /list to make a new active list or /clear to clear the current list\n'
        f'Use /td_on and /td_off to enable/disable timed entry deletion\n'
        f'Use /d_on and /d_off to enable/disable deletion of previous list\n'
        f'Use /reset to reset the chat\n'
        f'Use /unit_name (name) to change unit name'
    )
    return

def unitName(update: Update, context: CallbackContext) -> None:
    logger.info('changing unit name')
    bot = context.bot
    if(len(context.args)==1):
        context.chat_data['unit'] = str(context.args[0])
        # Edit active list
        try:
            bot.edit_message_text(
                chat_id=context.chat_data['cid'], 
                message_id=context.chat_data['ACTIVE'],
                text=generate_msg_text(Cases, context)
            )
        except:
            pass
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    return 

def generate_category_list(cdict, ctype, context):
    clist_text = ''
    ttext = type_text[ctype]
    outdated=[]
    td = False
    if('Cases' in context.chat_data):
        Cases = context.chat_data['Cases']
    # Optional time-based deletion
    if('td' in context.chat_data):
        if(context.chat_data['td']==True):
            td=True
    for i in enumerate(cdict.items(),1):
        index = i[0]
        rname = i[1][0]
        datestr = i[1][1][0]
        mc = i[1][1][1]
        mctext = ['Isolate at home till','5 days MC till']
        cdate = dateparser.parse(datestr, settings={'DATE_ORDER': 'DMY'})
        day5 = cdate + datetime.timedelta(days=4)
        day7 = cdate + datetime.timedelta(days=6)
        if(day7<datetime.datetime.now() and td):
            outdated.append(rname)
            continue
        cd = cdate.strftime('%d %b')
        d5 = day5.strftime('%d %b')
        d7 = day7.strftime('%d %b')
        clist_text += f'{str(index)}. {str(rname)}\n'
        if(ctype == 0 or ctype == 1):
            clist_text += (
                f'{ttext}{cd}. {mctext[mc]} {d5} (D5).\n'
                f'WFH till {d7} (D7) if ART positive on D5.\n\n'
            )
        elif(ctype == 2 or ctype == 3):
            clist_text += (
                f'{ttext}{cd}. WFH from {cd} (D1) till {d5} (D5).\n\n'
            )

    # Optional time-based deletion
    if(td):
        for t in outdated:
            cdict.pop(t)
        Cases[ct[ctype]]=cdict
        context.chat_data['Cases']=Cases
    
    num_cases = len(cdict)
    clist_text_prepend = f'({num_cases} cases)\n\n'
    clist_text = clist_text_prepend+clist_text
    return clist_text

def generate_msg_text(Cases,con):
    dtnow = datetime.datetime.now().strftime('%d %b %Y - %H%M hrs')
    unit_name = con.chat_data['unit']
    msg_text = (
        f'{unit_name} Outstanding Covid Incidents Summary\n\n'
        f'CAA {dtnow}\n\n'
        f'C+ {generate_category_list(Cases[CPos], CP, con)}'
        f'Ag+ {generate_category_list(Cases[APos], AP, con)}'
        f'HRW/HRN {generate_category_list(Cases[Hrn], HR, con)}'
        f'Known Contact {generate_category_list(Cases[CCon], CC, con)}'
        f'12FMD COVID CASE TRACKER\n'
        f'Use /add to add a case and /remove to remove.\n'
        f'Use /list to make a new active list.\n'
    )
        
    return msg_text

def addCaseType(update: Update, context: CallbackContext) -> int:
    logger.info('prompting for case type')  
    context.user_data.clear()
    command_msg = update.message.message_id
    context.user_data['com_msgid'] = command_msg
    '''Show new choice of buttons'''
    keyboard = [
        [
            InlineKeyboardButton('C+', callback_data=str(CP)),
            InlineKeyboardButton('Ag+', callback_data=str(AP)),
            InlineKeyboardButton('HRN', callback_data=str(HR)),
            InlineKeyboardButton('Close Contact', callback_data=str(CC)),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data['msgid'] = update.message.reply_text(
        text='Please state the type of case you are adding.', reply_markup=reply_markup
    ).message_id
    return TYPE

def mcStatus(update: Update, context: CallbackContext) -> int:
    """Show new choice of buttons"""
    query = update.callback_query
    ctype = query.data
    logger.info('Case submitted with type %s.', str(ctype))
    query.answer()
    context.user_data['case_type'] = int(ctype)
    keyboard = [
        [
            InlineKeyboardButton("YES", callback_data=str(ctype)+str(MC)),
            InlineKeyboardButton("NO", callback_data=str(ctype)+str(NM)),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text="MC taken?", reply_markup=reply_markup
    )
    return TYPE

def addCaseName(update: Update, context: CallbackContext) -> int:
    '''Show new choice of buttons'''
    query = update.callback_query
    ctype = query.data
    if(len(ctype)==1):
        logger.info('Case submitted with type %s.', str(ctype))  
        context.user_data['case_type'] = int(ctype)
        context.user_data['mc_type'] = int(NM)
    elif(len(ctype)==2):
        context.user_data['case_type'] = int(ctype[0])
        logger.info('Case submitted with type %s with MC option %s.', str(ctype[0]), str(ctype[1]))  
        context.user_data['mc_type'] = int(ctype[1])
    query.answer()
    query.edit_message_text(
        text='Enter case rank & name:'
    )
    return NAME

def addCaseDate(update: Update, context: CallbackContext) -> int:
    
    logger.info('at date prompt')
    cname = update.message.text
    context.user_data['case_name'] = str(cname)
    logger.info('Case submitted with name %s.', str(cname))
    bot = context.bot
    prompt_text = 'Enter case date:'
    try:
        bot.edit_message_text(chat_id=update.message.chat_id, message_id=context.user_data['msgid'], text=prompt_text)
    except:
        pass
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    return DATE

def caseDateHandler(update: Update, context: CallbackContext) -> int:
    cdate = update.message.text
    context.user_data['case_date'] = cdate
    logger.info('User entered case date %s.', str(cdate))
    cdt = dateparser.parse(cdate, settings={'DATE_ORDER': 'DMY'})
    bot = context.bot
    
    if(cdt is None) or (cdt>datetime.datetime.now()):
        logger.info('User entered invalid date.')
        context.user_data['case_date'] = 'rd'
        prompt_text = 'Invalid date entered. Enter case date in DD/MM/YY format:'
        try:
            bot.edit_message_text(chat_id=update.message.chat_id, message_id=context.user_data['msgid'], text=prompt_text)
        except:
            pass
        bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
        return DATE
    
    logger.info('Case submitted with date %s.', cdt.strftime('%d/%m/%Y'))
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['msgid'])
    bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['com_msgid'])
    ctype = context.user_data['case_type']
    cname = context.user_data['case_name']
    mc = context.user_data['mc_type']
    # lmao wtf is code readability
    # uses rank name of case as key for date
    # double nested dict because i have no brain
    # Cases = load_cases()
    if('Cases' in context.chat_data):
        Cases = context.chat_data['Cases']
    Cases[ct[ctype]][cname]=[cdt.strftime('%d/%m/%Y'),mc]
    context.chat_data['Cases'] = Cases
    
    # Edit active list
    bot.edit_message_text(
        chat_id=update.message.chat_id, 
        message_id=context.chat_data['ACTIVE'],
        text=generate_msg_text(Cases, context)
    )
    
    context.user_data.clear()
    return ConversationHandler.END

def cancelAdd(update: Update, context: CallbackContext) -> int:
    '''Returns `ConversationHandler.END`, which tells the
    ConversationHandler that the conversation is over.
    '''
    bot = context.bot
    query = update.callback_query
    if(query is not None):
        query.answer()
        msgid = query.message.message_id
        bot.delete_message(chat_id=update.message.chat_id, message_id=msgid)
    else:
        if('msgid' in context.user_data):
            bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['msgid'])
        bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    
    logger.info('User cancelled this action')
    bot.delete_message(chat_id=update.message.chat_id, message_id=context.user_data['com_msgid'])
    context.user_data.clear()
    return ConversationHandler.END


def remCaseType(update: Update, context: CallbackContext) -> int:
    logger.info('prompting for case type')  
    context.user_data.clear()
    command_msg = update.message.message_id
    com_cid = update.message.chat_id
    context.user_data['cid'] = com_cid
    context.user_data['com_msgid'] = command_msg
    '''Show new choice of buttons'''
    keyboard = [
        [
            InlineKeyboardButton('C+', callback_data=str(CP)),
            InlineKeyboardButton('Ag+', callback_data=str(AP)),
            InlineKeyboardButton('HRN', callback_data=str(HR)),
            InlineKeyboardButton('Close Contact', callback_data=str(CC)),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data['msgid'] = update.message.reply_text(
        text='Please state the type of case you are removing:', reply_markup=reply_markup
    ).message_id
    return TYPE

def remCaseName(update: Update, context: CallbackContext) -> int:
    '''Show new choice of buttons'''
    query = update.callback_query
    ctype = query.data
    logger.info('Case submitted with type %s.', str(ctype))  
    context.user_data['case_type'] = int(ctype)
    query.answer()
    if('Cases' in context.chat_data):
        Cases = context.chat_data['Cases']
    if(len(Cases[ct[int(ctype)]].keys())==0):
        keyboard = [
            [
                InlineKeyboardButton('C+', callback_data=str(CP)),
                InlineKeyboardButton('Ag+', callback_data=str(AP)),
                InlineKeyboardButton('HRN', callback_data=str(HR)),
                InlineKeyboardButton('Known Contact', callback_data=str(CC)),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            query.edit_message_text(
                text='No cases to remove, select another category or use /cancel to cancel:', reply_markup=reply_markup
            )
        except:
            pass
        return TYPE
    keyboard = [
        [
            InlineKeyboardButton(str(name), callback_data=str(name)) for name in Cases[ct[int(ctype)]].keys()
        ]
    ]   
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text='Select case rank & name:', reply_markup=reply_markup
    )
    return NAME

def remNameHandler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    cname= query.data
    logger.info('Case submitted with type %s.', str(cname))  
    query.answer()
    context.user_data['case_name'] = cname
    logger.info('User entered case name %s.', str(cname))
    
    bot = context.bot
    bot.delete_message(chat_id=context.user_data['cid'], message_id=context.user_data['msgid'])
    bot.delete_message(chat_id=context.user_data['cid'], message_id=context.user_data['com_msgid'])
    ctype = context.user_data['case_type']
    if('Cases' in context.chat_data):
        Cases = context.chat_data['Cases']
    Cases[ct[ctype]].pop(cname)
    context.chat_data['Cases'] = Cases
    
    # Edit active list
    bot.edit_message_text(
        chat_id=context.user_data['cid'], 
        message_id=context.chat_data['ACTIVE'],
        text=generate_msg_text(Cases, context)
    )
    
    context.user_data.clear()
    return ConversationHandler.END

def tdOn(update: Update, context: CallbackContext) -> None:
    logger.info('timed delete on')
    context.chat_data['td'] = True
    bot = context.bot
    if('Cases' in context.chat_data):
        Cases = context.chat_data['Cases']
    
    # Edit active list
    try:
        bot.edit_message_text(
            chat_id=update.message.chat_id, 
            message_id=context.chat_data['ACTIVE'],
            text=generate_msg_text(Cases, context)
        )
    except:
        pass
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    return 

def tdOff(update: Update, context: CallbackContext) -> None:
    logger.info('timed delete off')
    context.chat_data['td'] = False
    bot = context.bot
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    return 

def dOn(update: Update, context: CallbackContext) -> None:
    logger.info('delete on')
    context.chat_data['d'] = True
    bot = context.bot
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    return 

def dOff(update: Update, context: CallbackContext) -> None:
    logger.info('delete off')
    context.chat_data['d'] = False
    bot = context.bot
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    return 

def clear(update: Update, context: CallbackContext) -> None:
    logger.info('clear list')
    if('Cases' in context.chat_data):
        Cases = context.chat_data['Cases']
    for ctype in range(4):
        Cases[ct[ctype]].clear()
    context.chat_data['Cases'] = Cases
    chatid = context.user_data['cid']
    msgid = context.chat_data['ACTIVE']
    # Edit active list
    bot.edit_message_text(
        chat_id=chatid, 
        message_id=msgid,
        text=generate_msg_text(Cases, context)
    )
    bot = context.bot
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    return 

def reset(update: Update, context: CallbackContext) -> None:
    logger.info('clear list')
    context.chat_data.clear()
    bot = context.bot
    bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
    bot.send_message(chat_id=update.message.chat_id, text='Chat reset. Please use /start to resume')
    return 

def error_handler(update: object, context: CallbackContext) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f'An exception was raised while handling an update\n'
        f'<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}'
        '</pre>\n\n'
        f'<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n'
        f'<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n'
        f'<pre>{html.escape(tb_string)}</pre>'
    )

    # Finally, send the message
    context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=message, parse_mode=ParseMode.HTML)


def main() -> None:
    # Set these variable to the appropriate values
    TOKEN = "5249938330:AAF4vd0RX2Jdx_24vxDz3lSSWPUSWOOLRic"
    N = "covidtracker-bot-12"

    # Port is given by Heroku
    PORT = os.environ.get('PORT','5555')
    '''Run the bot.'''
    # Create the Updater and pass it your bot's token.
    DATABASE_URL = os.environ['DATABASE_URL'] #'postgres://fcoiknwokizqha:27e5045aa7b0291c9b91ab044b91ddd2ff8e06be37946ae5c09adfc570da57f3@ec2-3-225-79-57.compute-1.amazonaws.com:5432/d7nrhv19m54qjk'  
    DB_URL = DATABASE_URL.replace('postgres','postgresql',1)
    
    # conn = psycopg2.connect(dbname='d7nrhv19m54qjk', host='ec2-3-225-79-57.compute-1.amazonaws.com', port=5432, user='fcoiknwokizqha', password='27e5045aa7b0291c9b91ab044b91ddd2ff8e06be37946ae5c09adfc570da57f3', sslmode='require')
    
    pers = PostgresPersistence(url=DB_URL)
    updater = Updater(TOKEN, persistence=pers)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Setup conversation for adding cases
    add_handler = ConversationHandler(
        entry_points=[CommandHandler('add', addCaseType)],
        states={
            TYPE: [
                CallbackQueryHandler(mcStatus, pattern='^['+str(CP)+str(AP)+']$'),
                CallbackQueryHandler(addCaseName, pattern=
                    '^['+str(HR)+str(CC)+']$|^['+str(CP)+str(AP)+']['+str(NM)+str(MC)+']$'
                ),
            ],
            NAME: [
                MessageHandler(Filters.text & ~Filters.command, addCaseDate)
            ],
            DATE:   [
                MessageHandler(Filters.text & ~Filters.command, caseDateHandler)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancelAdd)],
        
    )

    # Add ConversationHandler to dispatcher that will be used for handling updates
    dispatcher.add_handler(add_handler)
    
    # Setup conversation for removing cases
    rem_handler = ConversationHandler(
        entry_points=[CommandHandler('remove', remCaseType)],
        states={
            TYPE: [
                CallbackQueryHandler(remCaseName, pattern='^['+str(HR)+str(CC)+str(CP)+str(AP)+']$'),
            ],
            NAME: [
                CallbackQueryHandler(remNameHandler),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancelAdd)],
    )
    # Add ConversationHandler to dispatcher that will be used for handling updates
    dispatcher.add_handler(rem_handler)
    
    # normal commands
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help))
    dispatcher.add_handler(CommandHandler('list', sl))
    
    dispatcher.add_handler(CommandHandler('clear', clear))
    dispatcher.add_handler(CommandHandler('reset', reset))
    dispatcher.add_handler(CommandHandler('unit_name', unitName))
    dispatcher.add_handler(CommandHandler('td_on', tdOn))
    dispatcher.add_handler(CommandHandler('td_off', tdOff))
    dispatcher.add_handler(CommandHandler('d_on', tdOn))
    dispatcher.add_handler(CommandHandler('d_off', tdOff))
    
    #Errors
    dispatcher.add_error_handler(error_handler)

    # Start the Bot
    
    # Start the webhook
    updater.start_webhook(listen="0.0.0.0",
                          port=int(PORT),
                          url_path=TOKEN,
                          webhook_url=f"https://{N}.herokuapp.com/{TOKEN}")
    
    # updater.start_polling()
    '''updater.start_webhook(listen="0.0.0.0",
                            port=int(PORT),
                            url_path=TOKEN)
    updater.bot.setWebhook('https://covidtracker-bot-12.herokuapp.com/' + TOKEN)'''
    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()