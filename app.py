from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, emit
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from bson import ObjectId
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'desiskill_secret_key_2026'
socketio = SocketIO(app)

client = MongoClient("mongodb://localhost:27017/")
db = client['desiskill']
skills_collection   = db['skills']
users_collection    = db['users']
requests_collection = db['requests']
matches_collection  = db['matches']
messages_collection = db['messages']

bcrypt = Bcrypt(app)

# ── Home ────────────────────────────────────────────────────
@app.route('/')
def home():
    return render_template('home.html', page_title='Home')

# ── Skills ──────────────────────────────────────────────────
@app.route('/skills')
def skills():
    search_term = request.args.get('search', '')
    if search_term:
        filtered = list(skills_collection.find({
            'title': {'$regex': search_term, '$options': 'i'}
        }))
    else:
        filtered = list(skills_collection.find())
    return render_template('skills.html', page_title='Skills',
                           skills=filtered, search_term=search_term)

# ── Register ────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form.get('name')
        email    = request.form.get('email')
        password = request.form.get('password')
        college  = request.form.get('college')
        existing = users_collection.find_one({'email': email})
        if existing:
            return render_template('register.html', page_title='Register',
                                   error='Email already registered!')
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        users_collection.insert_one({
            'name': name, 'email': email,
            'password': hashed_pw, 'college': college,
            'bio': '', 'skills_offered': [], 'skills_wanted': [],
            'created_at': datetime.now().strftime('%B %Y')
        })
        return redirect(url_for('login', success='Account created! Please login.'))
    return render_template('register.html', page_title='Register')

# ── Login ───────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    success = request.args.get('success', '')
    if request.method == 'POST':
        email    = request.form.get('email')
        password = request.form.get('password')
        user = users_collection.find_one({'email': email})
        if user and bcrypt.check_password_hash(user['password'], password):
            session['user_id']    = str(user['_id'])
            session['user_name']  = user['name']
            session['user_email'] = user['email']
            return redirect(url_for('dashboard'))
        return render_template('login.html', page_title='Login',
                               error='Wrong email or password!')
    return render_template('login.html', page_title='Login', success=success)

# ── Dashboard ───────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    my_requests = list(requests_collection.find(
        {'posted_by': session['user_name']}
    ))
    my_matches = list(matches_collection.find({
        '$or': [
            {'posted_by': session['user_name']},
            {'helped_by': session['user_name']}
        ]
    }))
    return render_template('dashboard.html', page_title='Dashboard',
                           user=user, my_requests=my_requests,
                           my_matches=my_matches)

# ── Profile ─────────────────────────────────────────────────
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    if request.method == 'POST':
        bio            = request.form.get('bio', '')
        skills_offered = [s.strip() for s in request.form.get('skills_offered', '').split(',') if s.strip()]
        skills_wanted  = [s.strip() for s in request.form.get('skills_wanted',  '').split(',') if s.strip()]
        users_collection.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$set': {'bio': bio, 'skills_offered': skills_offered,
                      'skills_wanted': skills_wanted}}
        )
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        return render_template('profile.html', page_title='Profile',
                               user=user, success='Profile updated!')
    return render_template('profile.html', page_title='Profile', user=user)

# ── Requests board ──────────────────────────────────────────
@app.route('/requests')
def view_requests():
    search_term = request.args.get('search', '')
    category    = request.args.get('category', '')
    query = {}
    if search_term:
        query['title'] = {'$regex': search_term, '$options': 'i'}
    if category:
        query['category'] = category
    all_requests = list(requests_collection.find(query).sort('created_at', -1))
    return render_template('requests.html', page_title='Requests',
                           requests=all_requests,
                           search_term=search_term,
                           category=category)

# ── Post a request ──────────────────────────────────────────
@app.route('/post-request', methods=['GET', 'POST'])
def post_request():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        title       = request.form.get('title')
        description = request.form.get('description')
        category    = request.form.get('category')
        offering    = request.form.get('offering', '')
        if not title or not description:
            return render_template('post_request.html',
                                   page_title='Post Request',
                                   error='Title and description required.')
        requests_collection.insert_one({
            'title': title, 'description': description,
            'category': category, 'offering': offering,
            'posted_by': session['user_name'],
            'user_id': session['user_id'],
            'status': 'open', 'offers': [],
            'created_at': datetime.now().strftime('%d %b %Y')
        })
        return redirect(url_for('view_requests'))
    return render_template('post_request.html', page_title='Post Request')

# ── Offer help ──────────────────────────────────────────────
@app.route('/offer/<request_id>')
def offer_help(request_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    skill_request = requests_collection.find_one({'_id': ObjectId(request_id)})
    if not skill_request:
        return redirect(url_for('view_requests'))
    already_offered = any(
        o['user_id'] == session['user_id']
        for o in skill_request.get('offers', [])
    )
    if not already_offered:
        requests_collection.update_one(
            {'_id': ObjectId(request_id)},
            {'$push': {'offers': {
                'user_id':    session['user_id'],
                'user_name':  session['user_name'],
                'offered_at': datetime.now().strftime('%d %b %Y')
            }}}
        )
    return redirect(url_for('view_requests'))

# ── Accept offer ────────────────────────────────────────────
@app.route('/accept/<request_id>/<helper_id>/<helper_name>')
def accept_offer(request_id, helper_id, helper_name):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    skill_request = requests_collection.find_one({'_id': ObjectId(request_id)})
    if not skill_request:
        return redirect(url_for('view_requests'))
    requests_collection.update_one(
        {'_id': ObjectId(request_id)},
        {'$set': {'status': 'matched', 'matched_with': helper_id}}
    )
    already_matched = matches_collection.find_one({
        'request_id': request_id, 'helped_by': helper_name
    })
    if not already_matched:
        matches_collection.insert_one({
            'request_id':    request_id,
            'request_title': skill_request['title'],
            'category':      skill_request['category'],
            'posted_by':     session['user_name'],
            'helped_by':     helper_name,
            'matched_at':    datetime.now().strftime('%d %b %Y'),
            'reviews':       []
        })
    return redirect(url_for('view_requests'))

# ── Decline offer ───────────────────────────────────────────
@app.route('/decline/<request_id>/<helper_id>')
def decline_offer(request_id, helper_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    requests_collection.update_one(
        {'_id': ObjectId(request_id)},
        {'$pull': {'offers': {'user_id': helper_id}}}
    )
    return redirect(url_for('view_requests'))

# ── My matches ──────────────────────────────────────────────
@app.route('/matches')
def my_matches():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    matches = list(matches_collection.find({
        '$or': [
            {'posted_by': session['user_name']},
            {'helped_by': session['user_name']}
        ]
    }))
    return render_template('my_matches.html', page_title='My Matches',
                           matches=matches)

# ── Chat ────────────────────────────────────────────────────
@app.route('/chat/<match_id>')
def chat(match_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    match = matches_collection.find_one({'_id': ObjectId(match_id)})
    if not match:
        return redirect(url_for('my_matches'))
    other_user = match['helped_by'] if match['posted_by'] == session['user_name'] else match['posted_by']
    messages   = list(messages_collection.find({'room': match_id}).sort('timestamp', 1))
    return render_template('chat.html', page_title='Chat',
                           match_id=match_id,
                           other_user=other_user,
                           room_id=match_id,
                           messages=messages)

# ── SocketIO events ─────────────────────────────────────────
socketio = SocketIO(app, cors_allowed_origins="*")
@socketio.on('join')
def on_join(data):
    join_room(data['room'])

@socketio.on('send_message')
def on_message(data):
    msg = {
        'room':      data['room'],
        'sender':    data['sender'],
        'message':   data['message'],
        'sent_at':   datetime.now().strftime('%H:%M'),
        'timestamp': datetime.now()
    }
    messages_collection.insert_one(msg)
    emit('receive_message', {
        'sender':  data['sender'],
        'message': data['message'],
        'sent_at': msg['sent_at']
    }, room=data['room'])

# ── Rate ────────────────────────────────────────────────────
@app.route('/rate/<match_id>', methods=['GET', 'POST'])
def rate(match_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    match = matches_collection.find_one({'_id': ObjectId(match_id)})
    if not match:
        return redirect(url_for('my_matches'))
    other_user = match['helped_by'] if match['posted_by'] == session['user_name'] else match['posted_by']
    already_rated = any(
        r['reviewer'] == session['user_name']
        for r in match.get('reviews', [])
    )
    if request.method == 'POST' and not already_rated:
        rating = int(request.form.get('rating', 5))
        review = request.form.get('review', '')
        matches_collection.update_one(
            {'_id': ObjectId(match_id)},
            {'$push': {'reviews': {
                'reviewer': session['user_name'],
                'rating':   rating,
                'comment':  review,
                'rated_at': datetime.now().strftime('%d %b %Y')
            }}}
        )
        users_collection.update_one(
            {'name': other_user},
            {'$push': {'ratings': rating}}
        )
        return redirect(url_for('my_matches'))
    return render_template('rate.html', page_title='Rate',
                           match_id=match_id,
                           other_user=other_user,
                           already_rated=already_rated)

# ── Logout ──────────────────────────────────────────────────
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ── Seed ────────────────────────────────────────────────────
@app.route('/seed')
def seed():
    skills_collection.delete_many({})
    sample_skills = [
        {'title': 'Python Programming', 'description': 'Basics, loops, functions and OOP.', 'category': 'Coding',      'offered_by': 'Utkarsh'},
        {'title': 'UI/UX Design',       'description': 'Figma, wireframing, clean UI.',     'category': 'Design',      'offered_by': 'Priya'},
        {'title': 'Mathematics',        'description': 'Calculus, algebra, statistics.',    'category': 'Academics',   'offered_by': 'Rahul'},
        {'title': 'Video Editing',      'description': 'Premiere Pro and CapCut.',          'category': 'Creative',    'offered_by': 'Sneha'},
        {'title': 'Public Speaking',    'description': 'Confidence and presentations.',     'category': 'Soft Skills', 'offered_by': 'Arjun'},
        {'title': 'Web Development',    'description': 'HTML, CSS and Flask basics.',       'category': 'Coding',      'offered_by': 'Meera'},
    ]
    skills_collection.insert_many(sample_skills)
    return 'Seeded! <a href="/skills">View Skills</a>'

if __name__ == '__main__':
    socketio.run(app, debug=False, port=5007)