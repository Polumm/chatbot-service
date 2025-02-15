from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    session_id = data.get("session_id", "")

    if not user_message:
        return jsonify({"response": "I didn't understand that."})

    # Mock bot response
    bot_reply = f"I'm your bot, responding to: {user_message}"

    return jsonify({"response": bot_reply})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
