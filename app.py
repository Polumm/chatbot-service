from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    session_id = data.get("session_id", "")

    # Simple mock response logic (Replace this with an actual AI model)
    response = "I'm your bot, responding to: " + user_message

    return jsonify({"response": response})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)  # Runs on localhost:5001
