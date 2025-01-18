# app.py
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import random
import json
import os
import pickle
from typing import Dict, List, Optional

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this in production

# Load custom word lists from JSON file
def load_word_lists():
    with open('data/word_lists.json', 'r') as f:
        return json.load(f)

# Load achievements from JSON file
def load_achievements():
    with open('data/achievements.json', 'r') as f:
        return json.load(f)

# Initialize data storage (in production, use a proper database)
users = {}
game_states = {}
leaderboards = {
    'classic': [],
    'time_attack': [],
    'word_count': []
}
active_multiplayer_games = {}

# Add practice session storage
practice_sessions: Dict[str, Dict] = {}

class GameMode:
    CLASSIC = 'classic'
    TIME_ATTACK = 'time_attack'
    WORD_COUNT = 'word_count'
    PRACTICE = 'practice'
    MULTIPLAYER = 'multiplayer'

class Achievement:
    def __init__(self, name, description, condition):
        self.name = name
        self.description = description
        self.condition = condition

    def check(self, stats):
        return self.condition(stats)

# Initialize achievements
achievements = [
    Achievement('Speed Demon', 'Reach 100 WPM', lambda stats: stats['max_wpm'] >= 100),
    Achievement('Marathon Runner', 'Complete 100 games', lambda stats: stats['games_played'] >= 100),
    Achievement('Perfect Game', 'Complete a game with 100% accuracy', lambda stats: stats['max_accuracy'] == 100),
    Achievement('Multiplayer Master', 'Win 10 multiplayer games', lambda stats: stats['multiplayer_wins'] >= 10),
]

def calculate_wpm(start_time, words_typed):
    elapsed_time = datetime.now() - start_time
    minutes = elapsed_time.total_seconds() / 10
    return int(words_typed / minutes) if minutes > 0 else 0

def calculate_accuracy(correct_words, total_words):
    return int((correct_words / total_words * 100) if total_words > 0 else 100)

def update_achievements(username):
    user = users[username]
    new_achievements = []
    
    for achievement in achievements:
        if achievement.name not in user['achievements'] and achievement.check(user['stats']):
            user['achievements'].append(achievement.name)
            new_achievements.append(achievement.name)
    
    return new_achievements

# Initialize users dictionary with persistence
def load_users():
    try:
        with open('data/users.pkl', 'rb') as f:
            return pickle.load(f)
    except (FileNotFoundError, EOFError):
        return {}

def save_users():
    os.makedirs('data', exist_ok=True)
    with open('data/users.pkl', 'wb') as f:
        pickle.dump(users, f)

# Initialize users at startup
users = load_users()

@app.route('/')
def index():
    if 'username' not in session:
        return render_template('index.html')
    return redirect(url_for('game_modes'))

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        flash('Please fill in all fields.')
        return redirect(url_for('index'))

    if username in users:
        flash('Username already exists.')
        return redirect(url_for('index'))

    # Initialize user with all required fields
    users[username] = {
        'password': password,
        'stats': {
            'games_played': 0,
            'total_words': 0,
            'correct_words': 0,
            'high_score': 0,
            'max_wpm': 0,
            'max_accuracy': 0,
            'multiplayer_games': 0,
            'multiplayer_wins': 0
        },
        'achievements': []
    }
    save_users()  # Save after registration
    
    flash('Registration successful! Please log in.')
    return redirect(url_for('index'))


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    if username in users and users[username]['password'] == password:
        session['username'] = username
        return redirect(url_for('game_modes'))

    flash('Invalid credentials.')
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Logged out successfully.')
    return redirect(url_for('index'))

@app.route('/game_modes')
def game_modes():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    # Filter only waiting games
    active_games = {
        game_id: game 
        for game_id, game in active_multiplayer_games.items() 
        if game['state'] == 'waiting'
    }
    
    return render_template('game_modes.html', active_games=active_games)

@app.route('/practice')
def practice():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    # Clear any existing practice session
    if 'practice' in session:
        session.pop('practice')
    
    return render_template('practice.html',
                         word_lists=load_word_lists(),
                         practice_active=False)

@app.route('/multiplayer/create')
def create_multiplayer():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    # Clean up old games
    current_time = datetime.now()
    for game_id in list(active_multiplayer_games.keys()):
        game = active_multiplayer_games[game_id]
        if ('start_time' in game and 
            (current_time - game['start_time']).total_seconds() > 3600):  # Remove games older than 1 hour
            active_multiplayer_games.pop(game_id)
    
    word_lists = load_word_lists()
    all_words = (word_lists['easy'] + 
                 word_lists['medium'] + 
                 word_lists['hard'])
    
    game_id = str(random.randint(1000, 9999))
    while game_id in active_multiplayer_games:  # Ensure unique game ID
        game_id = str(random.randint(1000, 9999))
    
    game = {
        'creator': session['username'],
        'players': [session['username']],
        'state': 'waiting',
        'words': random.sample(all_words, min(20, len(all_words))),
        'start_time': None,
        'scores': {}
    }
    active_multiplayer_games[game_id] = game
    
    return render_template('multiplayer_lobby.html', 
                         game_id=game_id,
                         game=game)

@app.route('/multiplayer/join', methods=['POST'])
def join_multiplayer():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    game_id = request.form.get('game_id')
    if not game_id or game_id not in active_multiplayer_games:
        flash('Game not found.')
        return redirect(url_for('game_modes'))
    
    game = active_multiplayer_games[game_id]
    if game['state'] != 'waiting':
        flash('Game already in progress.')
        return redirect(url_for('game_modes'))
    
    if session['username'] not in game['players']:
        game['players'].append(session['username'])
    
    return render_template('multiplayer_lobby.html', 
                         game_id=game_id,
                         game=game)

@app.route('/leaderboards')
def leaderboards_view():
    return render_template('leaderboards.html', leaderboards=leaderboards)

@app.route('/stats')
def stats():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    username = session['username']
    if username not in users:
        flash('User data not found. Please log in again.')
        return redirect(url_for('logout'))
    
    user_stats = users[username]['stats']
    achievements_earned = users[username].get('achievements', [])
    return render_template('stats.html', stats=user_stats, achievements=achievements_earned)

# More routes and game logic will be added here...
# routes.py (append to app.py)

@app.route('/game/<mode>')
def game(mode):
    if 'username' not in session:
        return redirect(url_for('index'))
    
    word_lists = load_word_lists()
    game_id = str(random.randint(1000000, 9999999))
    
    # Combine word lists to ensure we have enough words
    all_words = (word_lists['easy'] + 
                 word_lists['medium'] + 
                 word_lists['hard'])
    
    # Make sure we don't request more words than available
    max_words = min(100, len(all_words))
    
    game_state = {
        'mode': mode,
        'start_time': datetime.now(),
        'words': [],
        'current_index': 0,
        'correct_words': 0,
        'total_words': 0,
        'is_active': True
    }
    
    if mode == 'classic':
        game_state['time_left'] = 15
        game_state['words'] = random.sample(all_words, min(50, max_words))
    elif mode == 'time_attack':
        game_state['time_left'] = 10
        game_state['words'] = random.sample(all_words, min(100, max_words))
    elif mode == 'word_count':
        game_state['words'] = random.sample(all_words, min(50, max_words))
        # Don't set time_left for word_count mode
    
    game_states[game_id] = game_state
    
    # Prepare template variables
    template_vars = {
        'game_id': game_id,
        'mode': mode,
        'current_word': game_state['words'][0],
        'words_left': len(game_state['words']),
        'wpm': 0,
        'accuracy': 100
    }
    
    # Only add time_left for timed modes
    if mode in ['classic', 'time_attack']:
        template_vars['time_left'] = int(game_state['time_left'])
    
    return render_template('game.html', **template_vars)

@app.route('/submit_word', methods=['POST'])
def submit_word():
    game_id = request.form.get('game_id')
    game_state = game_states.get(game_id)
    
    if not game_state:
        return redirect(url_for('game_modes'))
    
    mode = game_state['mode']
    words_left = len(game_state['words']) - game_state['current_index']
    
    # Check game over conditions first
    game_over = False
    if mode in ['classic', 'time_attack']:
        game_over = game_state['time_left'] <= 0
    elif mode == 'word_count':
        game_over = words_left <= 0
    
    if game_over:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'game_over': True,
                'redirect_url': url_for('game_over', game_id=game_id)
            })
        return redirect(url_for('game_over', game_id=game_id))
    
    # Process word submission if game is not over
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        typed_word = request.form.get('typed_word')
        
        # Update game state based on typed word
        if game_state['current_index'] < len(game_state['words']):
            current_word = game_state['words'][game_state['current_index']]
            game_state['total_words'] += 1
            
            if typed_word == current_word:
                game_state['correct_words'] += 1
                if mode == 'time_attack':
                    game_state['time_left'] += 2
            
            game_state['current_index'] += 1

        # Calculate current stats
        wpm = calculate_wpm(game_state['start_time'], game_state['correct_words'])
        accuracy = calculate_accuracy(game_state['correct_words'], game_state['total_words'])
        words_left = len(game_state['words']) - game_state['current_index']

        # Check if game is over after processing word
        if mode in ['classic', 'time_attack']:
            game_over = game_state['time_left'] <= 0
        elif mode == 'word_count':
            game_over = words_left <= 0

        if game_over:
            return jsonify({
                'game_over': True,
                'redirect_url': url_for('game_over', game_id=game_id)
            })

        # Return updated game state
        response_data = {
            'current_word': game_state['words'][game_state['current_index']],
            'wpm': wpm,
            'accuracy': accuracy,
            'words_left': words_left,
            'game_over': False
        }

        if mode in ['classic', 'time_attack']:
            response_data['time_left'] = game_state['time_left']

        return jsonify(response_data)
    
    # Handle non-AJAX submissions - always include mode parameter
    return redirect(url_for('game', mode=mode))

def end_game(game_id):
    game_state = game_states[game_id]
    username = session.get('username')
    
    if not username or username not in users:
        flash('User session expired. Please login again.')
        return redirect(url_for('logout'))
    
    # Calculate final stats
    wpm = calculate_wpm(game_state['start_time'], game_state['correct_words'])
    accuracy = calculate_accuracy(game_state['correct_words'], game_state['total_words'])
    
    # Update user statistics
    user_stats = users[username]['stats']
    user_stats['games_played'] += 1
    user_stats['total_words'] += game_state['total_words']
    user_stats['correct_words'] += game_state['correct_words']
    user_stats['max_wpm'] = max(user_stats['max_wpm'], wpm)
    user_stats['max_accuracy'] = max(user_stats['max_accuracy'], accuracy)
    
    # Save updated user data
    save_users()
    
    # Update leaderboard
    leaderboard_entry = {
        'username': username,
        'wpm': wpm,
        'accuracy': accuracy,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    leaderboards[game_state['mode']].append(leaderboard_entry)
    leaderboards[game_state['mode']].sort(key=lambda x: x['wpm'], reverse=True)
    leaderboards[game_state['mode']] = leaderboards[game_state['mode']][:10]  # Keep top 10
    
    # Check for new achievements
    new_achievements = update_achievements(username)
    
    # Clean up game state
    game_states.pop(game_id, None)
    
    return render_template('game_over.html',
                         wpm=wpm,
                         accuracy=accuracy,
                         mode=game_state['mode'],
                         new_achievements=new_achievements)

# Multiplayer functionality
@app.route('/multiplayer/start', methods=['POST'])
def start_multiplayer():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    game_id = request.form.get('game_id')
    if not game_id or game_id not in active_multiplayer_games:
        flash('Game not found.')
        return redirect(url_for('game_modes'))
    
    game = active_multiplayer_games[game_id]
    if game['creator'] != session['username']:
        flash('Only the creator can start the game.')
        return redirect(url_for('game_modes'))
    
    game['state'] = 'in_progress'
    game['start_time'] = datetime.now()
    
    return render_template('game.html',
                         game_id=game_id,
                         mode='multiplayer',
                         current_word=game['words'][0],
                         words_left=len(game['words']))

@app.route('/multiplayer/update/<game_id>', methods=['POST'])
def update_multiplayer_game(game_id):
    if game_id not in active_multiplayer_games:
        return redirect(url_for('game_modes'))
    
    game = active_multiplayer_games[game_id]
    typed_word = request.form.get('typed_word').strip()
    player = session['username']
    
    current_word_index = game['player_stats'][player]['words_completed']
    if current_word_index >= len(game['words']):
        return jsonify({'game_over': True})
    
    if typed_word == game['words'][current_word_index]:
        game['player_stats'][player]['words_completed'] += 1
    
    # Check if any player has won
    if game['player_stats'][player]['words_completed'] >= len(game['words']):
        return end_multiplayer_game(game_id, player)
    
    return jsonify(game['player_stats'])

def end_multiplayer_game(game_id, winner):
    game = active_multiplayer_games[game_id]
    
    # Update stats for all players
    for player in game['players']:
        users[player]['stats']['multiplayer_games'] += 1
        if player == winner:
            users[player]['stats']['multiplayer_wins'] += 1
    
    # Clean up game
    del active_multiplayer_games[game_id]
    
    return render_template('multiplayer_results.html',
                         winner=winner,
                         stats=game['player_stats'])

@app.route('/practice/submit', methods=['POST'])
def submit_practice_word():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    typed_word = request.form.get('typed_word', '').strip()
    practice_state = session.get('practice')
    
    if not practice_state:
        return redirect(url_for('practice'))
    
    current_word = practice_state['words'][practice_state['current_index']]
    practice_state['words_completed'] += 1
    
    if typed_word == current_word:
        practice_state['correct_words'] += 1
    
    practice_state['current_index'] += 1
    
    # Check if we've reached the end of the word list
    if practice_state['current_index'] >= len(practice_state['words']):
        practice_state['current_index'] = 0  # Loop back to beginning
    
    # Calculate accuracy
    accuracy = (practice_state['correct_words'] / practice_state['words_completed'] * 100) if practice_state['words_completed'] > 0 else 100
    
    # Update session
    session['practice'] = practice_state
    
    return render_template('practice.html',
                         word_lists=load_word_lists(),
                         practice_active=True,
                         current_word=practice_state['words'][practice_state['current_index']],
                         words_completed=practice_state['words_completed'],
                         accuracy=round(accuracy, 1))

@app.route('/practice/start', methods=['POST'])
def start_practice():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    word_list = request.form.get('word_list')
    word_lists = load_word_lists()
    
    if word_list.startswith('custom_'):
        list_name = word_list[7:]  # Remove 'custom_' prefix
        practice_words = word_lists['custom_lists'][list_name]
    else:
        practice_words = word_lists[word_list]
    
    # Initialize practice session
    session['practice'] = {
        'words': practice_words,
        'current_index': 0,
        'words_completed': 0,
        'correct_words': 0
    }
    
    return render_template('practice.html',
                         word_lists=word_lists,
                         practice_active=True,
                         current_word=practice_words[0],
                         words_completed=0,
                         accuracy=100)

# Add session checking to all protected routes
@app.before_request
def check_session():
    protected_routes = ['game_modes', 'game', 'practice', 'stats', 'submit_word']
    if (request.endpoint in protected_routes and 
        'username' in session and 
        session['username'] not in users):
        session.clear()
        flash('Session expired. Please login again.')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)