from flask import Flask, request, jsonify
import os
import google.generativeai as genai
import jwt  # Import JWT for verification
from dotenv import load_dotenv
import requests

# Load API Key from .env
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")  # Ensure it matches the main app
DB_SERVICE_URL = os.getenv("DB_SERVICE_URL")

if not DB_SERVICE_URL:
    raise ValueError("Missing DB_SERVICE_URL in environment variables")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

app = Flask(__name__)

def verify_jwt(token):
    """Verify JWT token"""
    try:
        decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        print(f"✅ Debug: Token decoded successfully! {decoded}")
        return decoded
    except jwt.ExpiredSignatureError:
        print("❌ Debug: Token expired!")
        return None
    except jwt.InvalidTokenError:
        print("❌ Debug: Invalid token!")
        return None

@app.route("/chat", methods=["POST"])
def chat():
    # ✅ Get token
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else None
    print(f"🟡 Debug: Received token: {token}")

    if not token or not verify_jwt(token):
        return jsonify({"response_type": "text", "response": "Unauthorized: Invalid or missing token."}), 401

    # ✅ Token is valid, continue processing
    data = request.json
    user_message = data.get("message", "").strip().lower()
    session_id = data.get("session_id", "")
    conversation_state = data.get("conversation_state", {})

    print(f"🟡 Debug: Received conversation state → {conversation_state}")
    print(f"🟡 Debug: Received user message → {user_message}")

    # ✅ Retrieve user ID
    decoded_token = verify_jwt(token)
    if not decoded_token:
        return jsonify({"response_type": "text", "response": "Unauthorized: Invalid token."}), 401

    user_id = decoded_token.get("user_id")  
    print(f"✅ Debug: Authenticated as user_id: {user_id}")

    if not user_id:
        return jsonify({"response_type": "text", "response": "Unauthorized: Missing user information."}), 401

    # ✅ Step 1: Ask for Friends Selection
    if "step" not in conversation_state:
        conversation_state["step"] = "select_friends"
        print(f"🟡 Debug: Asking user to select friends...")

        try:
            friends_resp = requests.get(f"{DB_SERVICE_URL}/friends/list?user_id={user_id}", timeout=5)
            if friends_resp.status_code == 200:
                friends_list = friends_resp.json().get("friends", [])
            else:
                return jsonify({"response_type": "text", "response": "Error fetching friends list from database."})
        except requests.exceptions.RequestException:
            return jsonify({"response_type": "text", "response": "Database service unavailable."})

        return jsonify(
            {
                "response_type": "multiple_choice",
                "prompt": "Which friends do you want to have a movie night with? (Select 1-5)",
                "options": [friend["username"] for friend in friends_list],
                "conversation_state": conversation_state,  # ✅ Return updated state
            }
        )

    # ✅ Step 2: Process Friend Selection
    elif conversation_state.get("step") == "select_friends":  # ✅ Fix here
        print(f"🟡 Debug: Processing friend selection...")
        print(f"🟡 Debug: Raw user message → {user_message}")

        selected_friends = [f.strip() for f in user_message.split(",") if f.strip()]
        print(f"✅ Debug: Processed selected friends → {selected_friends}")

        if len(selected_friends) > 5:
            return jsonify({
                "response_type": "text",
                "response": "You can select up to 5 friends. Please try again.",
                "conversation_state": conversation_state,
            })

        conversation_state["friends"] = selected_friends  
        conversation_state["step"] = "fetch_movies"  # ✅ Ensure next step is set

        print(f"✅ Debug: Friends selected → {conversation_state['friends']}")

        return jsonify({
            "response_type": "text",
            "response": f"Got it! Fetching movies saved by: {', '.join(conversation_state['friends'])}.",
            "conversation_state": conversation_state,  # ✅ Return updated state
        })

    # ✅ Step 3: Fetch Movies & Genres
    elif conversation_state.get("step") == "fetch_movies":
        try:
            selected_friends_param = ",".join(conversation_state["friends"])
            movies_resp = requests.get(f"{DB_SERVICE_URL}/movies/list?user_id={user_id}&friends={selected_friends_param}", timeout=5)

            if movies_resp.status_code == 200:
                saved_movies = movies_resp.json().get("saved_movies", [])
            else:
                return jsonify({"response_type": "text", "response": "Could not fetch saved movies."})

            if not saved_movies:
                return jsonify({"response_type": "text", "response": "None of your friends have saved movies. Try selecting different friends or adding movies to your list."})

            available_genres = list(set(movie.get("genre", "Unknown") for movie in saved_movies))

            conversation_state["movies"] = saved_movies
            conversation_state["genres"] = available_genres
            conversation_state["step"] = "select_genre"

            return jsonify(
                {
                    "response_type": "multiple_choice",
                    "prompt": "Here are the genres that you and your selected friends have saved movies in. Pick one to watch:",
                    "options": available_genres,
                    "conversation_state": conversation_state,
                }
            )

        except requests.exceptions.RequestException:
            return jsonify({"response_type": "text", "response": "Error retrieving saved movies from the database."})

    # ✅ Step 3: Ask for User's Mood
    elif conversation_state["step"] == "select_genre":
        conversation_state["genre"] = user_message.capitalize()
        conversation_state["step"] = "select_mood"

        return jsonify(
            {
                "response_type": "multiple_choice",
                "prompt": "What is your mood today?",
                "options": ["Happy", "Sad", "Excited", "Relaxed"],
                "conversation_state": conversation_state,
            }
        )

    # ✅ Step 4: Send Data to Gemini for a Movie Recommendation
    elif conversation_state["step"] == "select_mood":
        conversation_state["mood"] = user_message.capitalize()
        conversation_state["step"] = "query_gemini"

        filtered_movies = [m for m in conversation_state["movies"] if m.get("genre") == conversation_state["genre"]]

        recommendation = query_gemini(conversation_state["genre"], conversation_state["mood"], filtered_movies)

        return jsonify(
            {
                "response_type": "text",
                "response": f"Based on your selected genre ({conversation_state['genre']}), your mood ({conversation_state['mood']}), and your friends' saved movies, I recommend: {recommendation}. Enjoy your movie night!",
                "conversation_state": conversation_state,
            }
        )

    return jsonify({"response_type": "text", "response": "I didn't understand that."})


def query_gemini(genre, mood, movies):
    if not movies:
        return "There are no saved movies in this genre among your selected friends."

    movie_list_text = "\n".join([f"- {m['title']} ({m.get('genre', 'Unknown')})" for m in movies])

    prompt = f"""
    You are a movie recommendation assistant.
    A group of friends is planning a movie night.

    - Genre: {genre}
    - Mood: {mood}
    - Available Movies:
      {movie_list_text}

    Recommend one movie from the list.
    """

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        return response.text
    except Exception:
        return "Error contacting Gemini."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6002, debug=True)
