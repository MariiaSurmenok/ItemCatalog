from flask import Flask, render_template, url_for, jsonify, session, request, make_response, redirect, flash
from sqlalchemy import create_engine, asc, desc

from sqlalchemy.orm import sessionmaker
from database_setup import Base, User, Category, Item

import httplib2, json, requests, random, string
from functools import wraps

app = Flask(__name__)

# Connect DB.
engine = create_engine('postgresql://vagrant@/catalog')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
db_session = DBSession()


# Decorators
def user_logged_in(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if session['user_id']:
            return function(*args, **kwargs)
        else:
            return redirect(url_for('login'))
    return wrapper


# Handle pages.
@app.route('/')
@app.route('/catalog/')
def index():
    categories = db_session.query(Category).order_by(Category.name)
    last_items = db_session.query(Item).order_by(desc(Item.id)).limit(10)

    return render_template('index.html', categories=categories, items=last_items)


@app.route('/catalog/<category_name>/')
def showCategory(category_name):
    categories = db_session.query(Category).order_by(Category.name)
    current_category = db_session.query(Category).filter_by(name=category_name).one()
    items = db_session.query(Item).filter_by(category_id=current_category.id).all()

    return render_template('category.html', items=items,
                           current_category=current_category, categories=categories)


@app.route('/catalog/<category_name>/<item_name>/')
def viewItem(category_name, item_name):
    current_category = db_session.query(Category).filter_by(name=category_name).one()
    item = db_session.query(Item).filter_by(category_id=current_category.id, name=item_name).one()
    return render_template('item.html', item=item)


@app.route('/catalog/new/', methods=['GET', 'POST'])
@user_logged_in
def addNewItem():
    categories = db_session.query(Category).order_by(Category.name)
    if request.method == 'GET':
        return render_template('create_item.html', categories=categories, info=None)
    if request.method == 'POST':
        item_name = request.form['item_name']
        description = request.form['description']
        category_id = request.form['category_id']
        # check that item_name is not empty, create flash if it is empty
        if not item_name:
            info = dict()
            info['error'] = 'Name cannot be empty'
            info['description'] = description
            info['cat_id'] = category_id
            return render_template('create_item.html', categories=categories, info=info)
        new_item = Item(name=item_name, description=description, category_id=category_id, user_id=session['user_id'])
        db_session.add(new_item)
        db_session.commit()
        flash('New item: "%s" added' % item_name)
    return redirect(url_for('index'))


@app.route('/catalog/<item_name>/edit')
def editItem(item_name):
    pass


@app.route('/catalog/<item_name>/delete/')
def deleteItem(item_name):
    pass


@app.route('/login/')
def login():
    state = ''.join([random.choice(string.ascii_letters + string.digits) for x in range(0, 32)])
    session['state'] = state
    return render_template('login.html', state=state)


@app.route('/disconnect/')
def disconnect():
    provider = session.get('provider')
    if provider:
        if provider == 'facebook':
            fbdisconnect()
            del session['facebook_id']
        del session['name']
        del session['email']
        del session['picture']
        del session['user_id']
        del session['provider']
        flash('You were successfully logged out.')

    return redirect(url_for('index'))


# Facebook OAuth
@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    access_token = request.data
    app_id = json.loads(open('fb_client_secrets.json', 'r').read())['web']['app_id']
    app_secret = json.loads(open('fb_client_secrets.json', 'r').read())['web']['app_secret']

    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' %\
          (app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    token = result.split(',')[0].split(':')[1].replace('"', '')
    url = 'https://graph.facebook.com/v2.8/me?access_token=%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    data = json.loads(result)
    print(data)
    session['provider'] = 'facebook'
    session['name'] = data['name']
    session['email'] = data['email']
    session['facebook_id'] = data['id']
    session['access_token'] = access_token


    # Get user picture.
    url = 'https://graph.facebook.com/v2.8/me/picture?access_token=%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    session['picture'] = data["data"]["url"]

    user_id = getUserID(session['email'])
    if not user_id:
        createUser(session)
    session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += session['name']

    output += '!</h1>'
    output += '<img src="'
    output += session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash('You were successfully logged in as %s' % session['name'])
    return output


@app.route('/fbdisconnect/')
def fbdisconnect():
    facebook_id = session['facebook_id']
    access_token = session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (facebook_id, access_token)
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]
    return 'You have been logged out'



# JSON API.
@app.route('/catalog.json/')
def getCatalogJSON():
    categories = db_session.query(Category).all()
    return jsonify(Category=[createCategoryDict(category) for category in categories])


@app.route('/<category_name>.json/')
@app.route('/catalog/<category_name>.json/')
def getCategoryJSON(category_name):
    category = db_session.query(Category).filter_by(name=category_name).one()
    return jsonify(Category=createCategoryDict(category))


@app.route('/<category_name>/<item_name>.json/')
@app.route('/catalog/<category_name>/<item_name>.json/')
def getItemJSON(category_name, item_name):
    category = db_session.query(Category).filter_by(name=category_name).one()
    item = db_session.query(Item).filter_by(name=item_name, category=category).one()
    return jsonify(Item=item.serialize)


# JSON helper functions.
def createCategoryDict(category):
    serialized_category = category.serialize

    items = db_session.query(Item).filter_by(category_id=category.id).all()
    if items:
        serialized_category['items'] = [item.serialize for item in items]
    return serialized_category


# User helper functions.
def createUser(session):
    new_user = User(name=session['name'], email=session['email'], picture=session['picture'])
    db_session.add(new_user)
    db_session.commit()
    user = db_session.query(User).filter_by(email=session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = db_session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = db_session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


# At the end start Flask app.
if __name__ == '__main__':
    app.secret_key = 'ADD YOUR SECRET KEY HERE'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
