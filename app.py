from flask import Flask, request, jsonify, session
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr
import os
import jwt  # Import JWT for verification
from dotenv import load_dotenv
import requests

# Only load .env in development mode (Optional)
if os.getenv("FLASK_ENV") == "development":
    load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")  # Must match whatever you use for JWT
DB_SERVICE_URL = os.getenv("DB_SERVICE_URL")
if not DB_SERVICE_URL:
    raise ValueError("Missing DB_SERVICE_URL in environment variables")

# Configure Gemini
# genai.configure(api_key=GEMINI_API_KEY)
app = Flask(__name__)
app.secret_key = SECRET_KEY  # Needed for Flask session to work


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
    # ---------------------------------------------------------------------
    # 1) Verify the JWT
    # ---------------------------------------------------------------------
    auth_header = request.headers.get("Authorization", "")
    token = (
        auth_header.replace("Bearer ", "")
        if auth_header.startswith("Bearer ")
        else None
    )
    print(f"🟡 Debug: Received token: {token}")
    if not token:
        return jsonify(
            {
                "response_type": "text",
                "response": "Unauthorized: Missing token.",
            }
        ), 401
    decoded_token = verify_jwt(token)
    if not decoded_token:
        return jsonify(
            {
                "response_type": "text",
                "response": "Unauthorized: Invalid token.",
            }
        ), 401
    user_id = decoded_token.get("user_id")
    print(f"✅ Debug: Authenticated as user_id: {user_id}")
    if not user_id:
        return jsonify(
            {
                "response_type": "text",
                "response": "Unauthorized: Missing user information.",
            }
        ), 401
    user_key = str(user_id)

    # ---------------------------------------------------------------------
    # 2) Retrieve the session_id from the request and isolate conversation state
    # ---------------------------------------------------------------------
    data = request.json
    session_id = data.get("session_id", "").strip()
    if not session_id:
        return jsonify(
            {"response_type": "text", "response": "Missing session_id."}
        ), 400

    # Initialize state as a nested dict: state[user_id][session_id]
    if "conversation_state" not in session:
        session["conversation_state"] = {}
    if user_key not in session["conversation_state"]:
        session["conversation_state"][user_key] = {}
    if session_id not in session["conversation_state"][user_key]:
        session["conversation_state"][user_key][session_id] = {}
    conversation_state = session["conversation_state"][user_key][session_id]

    # ---------------------------------------------------------------------
    # 3) Check for a reset command to restart the conversation flow
    # ---------------------------------------------------------------------
    user_message = data.get("message", "").strip().lower()
    if user_message == "reset":
        session["conversation_state"][user_key][session_id] = {}
        conversation_state = session["conversation_state"][user_key][
            session_id
        ]
        conversation_state["step"] = "select_friends"
        try:
            friends_resp = requests.get(
                f"{DB_SERVICE_URL}/friends/list?user_id={user_id}", timeout=5
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
        response_json = {
            "response_type": "multiple_choice",
            "prompt": "Conversation reset. Which friends do you want to have a movie night with? (Select 1-5)",
            "options": [friend["username"] for friend in friends_list],
        }
        session.modified = True
        return jsonify(response_json)

    print(f"🟡 Debug: Current conversation state → {conversation_state}")
    print(f"🟡 Debug: Received user message → {user_message}")

    # ---------------------------------------------------------------------
    # 4) Process the conversation steps
    # ---------------------------------------------------------------------
    # Step 1: Ask for Friends Selection
    if "step" not in conversation_state:
        conversation_state["step"] = "select_friends"
        try:
            friends_resp = requests.get(
                f"{DB_SERVICE_URL}/friends/list?user_id={user_id}", timeout=5
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
        response_json = {
            "response_type": "multiple_choice",
            "prompt": "Which friends do you want to have a movie night with? (Select 1-5)",
            "options": [friend["username"] for friend in friends_list],
        }
    # Step 2: Process Friend Selection and automatically fetch movies
    elif conversation_state.get("step") == "select_friends":
        selected_friends = [
            f.strip() for f in user_message.split(",") if f.strip()
        ]
        if len(selected_friends) > 5:
            response_json = {
                "response_type": "text",
                "response": "You can select up to 5 friends. Please try again. If you want to restart, type 'reset'.",
            }
        else:
            conversation_state["friends"] = selected_friends
            # Immediately fetch movies after friend selection
            try:
                selected_friends_param = ",".join(selected_friends)
                movies_resp = requests.get(
                    f"{DB_SERVICE_URL}/movies/list?user_id={user_id}&friends={selected_friends_param}",
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
                print(saved_movies)
                if not saved_movies:
                    response_json = {
                        "response_type": "text",
                        "response": "None of your friends have saved movies. Try selecting different friends or adding movies to your list. If you want to restart, type 'reset'.",
                    }
                else:
                    # Store the list of movie names for recommendation
                    movie_names = [
                        movie.get("title", "Unknown") for movie in saved_movies
                    ]
                    conversation_state["movies"] = (
                        saved_movies  # full movie objects for logging if needed
                    )
                    conversation_state["movie_names"] = movie_names
                    conversation_state["step"] = "select_genre"
                    # Predefined genre options (or user can type their own)
                    predefined_genres = [
                        "Action",
                        "Comedy",
                        "Drama",
                        "Horror",
                        "Sci-Fi",
                        "Romance",
                    ]
                    response_json = {
                        "response_type": "multiple_choice",
                        "prompt": "Please select your preferred genre for tonight's movie from the options below, or type your own:",
                        "options": predefined_genres,
                    }
            except requests.exceptions.RequestException:
                response_json = {
                    "response_type": "text",
                    "response": "Error retrieving saved movies from the database.",
                }
    # Step 3: Process Genre Selection and Ask for Mood
    elif conversation_state.get("step") == "select_genre":
        conversation_state["genre"] = user_message.capitalize()
        conversation_state["step"] = "select_mood"
        response_json = {
            "response_type": "multiple_choice",
            "prompt": "What is your mood today?",
            "options": ["Happy", "Sad", "Excited", "Relaxed"],
        }
    # Step 4: Process Mood and Query Gemini for a Recommendation
    elif conversation_state.get("step") == "select_mood":
        conversation_state["mood"] = user_message.capitalize()
        conversation_state["step"] = "query_gemini"
        # Use the stored movie names (all movies from DB) for the recommendation prompt
        movie_names = conversation_state.get("movie_names", [])
        recommendation = query_gemini(
            conversation_state["genre"],
            conversation_state["mood"],
            movie_names,
        )
        response_json = {
            "response_type": "text",
            "response": (
                f"Based on your preferred genre ({conversation_state['genre']}), "
                f"your mood ({conversation_state['mood']}), and your friends' saved movies, "
                f"I recommend: {recommendation}. Enjoy your movie night!"
            ),
        }
    # Default: Unexpected Message or Unknown Step
    else:
        response_json = {
            "response_type": "text",
            "response": "I didn't understand that. If you want to restart the conversation, please type 'reset'.",
        }

    # ---------------------------------------------------------------------
    # 5) Save the updated conversation state and return the response
    # ---------------------------------------------------------------------
    session["conversation_state"][user_key][session_id] = conversation_state
    session.modified = True
    return jsonify(response_json)


def query_gemini(genre, mood, movie_names):
    if not movie_names:
        return "There are no saved movies among your selected friends."
    movie_list_text = "\n".join([f"- {name}" for name in movie_names])
    prompt = f"""
    You are a movie recommendation assistant.
    A group of friends is planning a movie night.
    - Preferred Genre: {genre}
    - Mood: {mood}
    - Some Movies they already seen and liked (find some other movies they might like):
      {movie_list_text}
    Recommend one movie from the list.
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from pydantic import SecretStr
        import os

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",  # or another supported model
            api_key=SecretStr(os.getenv("GEMINI_API_KEY")),
        )
        # Use the new invoke method
        response = llm.invoke(prompt)
        return response
    except Exception as e:
        print("Gemini error:", e)
        return "Sorry, I couldn't generate a recommendation at this time. Please try again later."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6002, debug=True)
