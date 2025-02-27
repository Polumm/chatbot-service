from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    session_id = data.get("session_id", "")

    if not user_message:
        return jsonify(
            {"response_type": "text", "response": "I didn't understand that."}
        )

    # Determine response type based on user message
    if "color" in user_message.lower():
        bot_reply = {
            "response_type": "multiple_choice",
            "prompt": "Which color do you prefer?",
            "options": ["Red", "Green", "Blue"],
        }
    elif "name" in user_message.lower():
        bot_reply = {
            "response_type": "fill_in",
            "prompt": "What is your name?",
            "placeholder": "Type your name here...",
        }
    else:
        bot_reply = {
            "response_type": "text",
            "response": "Hello! I am here to assist you.",
        }

    return jsonify(bot_reply)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6002, debug=True)
