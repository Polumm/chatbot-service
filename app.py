from flask import Flask, request, jsonify
import os
import google.generativeai as genai
import jwt  # Import JWT for verification
from dotenv import load_dotenv
import requests

# Load API Key from .env
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")  # Make sure the secret key is the same as the main app
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
        return decoded
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

@app.route("/chat", methods=["POST"])
def chat():
    """
    Handles chatbot conversation for movie night planning.
    """
    # ✅ Get token from request headers
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else None

    if not token or not verify_jwt(token):
        return jsonify({"response_type": "text", "response": "Unauthorized: Invalid or missing token."}), 401

    # ✅ Token is valid, continue processing
    data = request.json
    user_message = data.get("message", "").lower()
    session_id = data.get("session_id", "")
    conversation_state = data.get("conversation_state", {})

    # ✅ Retrieve user ID from token
    decoded_token = verify_jwt(token)
    user_id = decoded_token.get("username")

    if not user_id:
        return jsonify({"response_type": "text", "response": "Unauthorized: Missing user information."}), 401

    # ✅ Step 1: Ask for Friends Selection (Max 3)
    if "step" not in conversation_state:
        conversation_state["step"] = "select_friends"
        # ✅ Fetch friends from database
        try:
            friends_resp = requests.get(
                f"{DB_SERVICE_URL}/friends?user_id={user_id}", timeout=5
            )
            if friends_resp.status_code == 200:
                friends_list = friends_resp.json().get("friends", [])
            else:
                return jsonify(
                    {
                        "response_type": "text",
                        "response": "Error fetching friends list from database.",
                    }
                )
        except requests.exceptions.RequestException:
            return jsonify(
                {
                    "response_type": "text",
                    "response": "Database service unavailable.",
                }
            )

        return jsonify(
            {
                "response_type": "multiple_choice",
                "prompt": "Which friends do you want to have a movie night with? (Select up to 3)",
                "options": [friend["username"] for friend in friends_list],
                "conversation_state": conversation_state,
            }
        )

    # ✅ Step 2: Retrieve Friends' Saved Movies and Extract Available Genres
    elif conversation_state["step"] == "select_friends":
        conversation_state["friends"] = user_message.split(", ")
        conversation_state["step"] = "fetch_movies"

        # ✅ Retrieve saved movies from the selected friends and user
        try:
            selected_friends = ",".join(conversation_state["friends"])
            movies_resp = requests.get(
                f"{DB_SERVICE_URL}/movies/list?user_id={user_id}&friends={selected_friends}",
                timeout=5,
            )

            if movies_resp.status_code == 200:
                saved_movies = movies_resp.json().get("saved_movies", [])
            else:
                return jsonify(
                    {
                        "response_type": "text",
                        "response": "Could not fetch saved movies.",
                    }
                )

            if not saved_movies:
                return jsonify(
                    {
                        "response_type": "text",
                        "response": "None of your friends have saved movies. Try selecting different friends or adding movies to your list.",
                        "conversation_state": conversation_state,
                    }
                )

            # ✅ Extract unique genres (If Not Stored in DB, Fetch From TMDB)
            available_genres = list(
                set(movie.get("genre", "Unknown") for movie in saved_movies)
            )

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
            return jsonify(
                {
                    "response_type": "text",
                    "response": "Error retrieving saved movies from the database.",
                    "conversation_state": conversation_state,
                }
            )

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

        # ✅ Filter movies based on selected genre
        filtered_movies = [
            m
            for m in conversation_state["movies"]
            if m.get("genre") == conversation_state["genre"]
        ]

        # ✅ Call Gemini for a recommendation
        recommendation = query_gemini(
            conversation_state["genre"],
            conversation_state["mood"],
            filtered_movies,
        )

        return jsonify(
            {
                "response_type": "text",
                "response": f"Based on your selected genre ({conversation_state['genre']}), your mood ({conversation_state['mood']}), and your friends' saved movies, I recommend: {recommendation}. Enjoy your movie night!",
                "conversation_state": conversation_state,
            }
        )

    return jsonify(
        {"response_type": "text", "response": "I didn't understand that."}
    )


def query_gemini(genre, mood, movies):
    """
    Sends the genre, mood, and saved movies to Gemini API for a movie recommendation.
    Only recommends movies from the provided list.
    """
    if not movies:
        return "There are no saved movies in this genre among your selected friends. Try choosing another genre or different friends."

    # ✅ Format movies properly for Gemini prompt
    movie_list_text = "\n".join(
        [f"- {m['title']} ({m.get('genre', 'Unknown')})" for m in movies]
    )

    prompt = f"""
    You are a movie recommendation assistant.
    A group of friends is planning a movie night.
    
    - Genre: {genre}
    - Mood: {mood}
    - Available Movies:
      {movie_list_text}

    Recommend **one movie** from the list that best matches the mood.
    Respond with **only the movie title** and a short tagline.
    """

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return "Error contacting Gemini. Try again later."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6002, debug=True)
