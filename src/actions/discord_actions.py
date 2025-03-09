from src.action_handler import register_action
from src.helpers import print_h_bar
import os
from dotenv import load_dotenv
import json

load_dotenv()

DEPLOY_TOKEN_URL = os.getenv("DEPLOY_TOKEN_URL")


@register_action("list-channels")
def list_channels(agent, **kwargs) -> dict:
    list_channels = agent.connection_manager.perform_action(
        connection_name="discord",
        action_name="list-channels",
        params=[]
    )

    return list_channels


@register_action("read-mentioned-messages")
def read_mentioned_messages(agent, **kwargs) -> list:
    list_channels = agent.connection_manager.perform_action(
        connection_name="discord",
        action_name="list-channels",
        params=[]
    )
    agent.logger.info(list_channels)
    list_messages = []
    for channel in list_channels:
        mentioned_messages = agent.connection_manager.perform_action(
            connection_name="discord",
            action_name="read-mentioned-messages",
            params=[channel["id"], 1]
        )
        agent.logger.info(mentioned_messages)
        if mentioned_messages:
            list_messages.append(mentioned_messages[0])
    return list_messages


@register_action("deploy-token-discord")
def deploy_token_discord(agent, **kwargs):
    agent.logger.info("\n📝 Deploying token with discord")
    print_h_bar()
    # url = f"{DEPLOY_TOKEN_URL}api/memecoin/create-for-user"

    messages = read_mentioned_messages(agent, **kwargs)

    responses = []
    for message in messages:
        agent.logger.info(message)
        # data = {
        #     "isTwitter": True,
        #     "twitterHandle": tweet.get('username'),
        #     "input": tweet.get('text'),
        # }
        # response = requests.post(url, data=data)
        response = {
            "success": True,
            "message": "Token created successfully",
            "transactionHash": "0x0b44610182edfb449248456ed0e0bf0b13cb12ccda2a143d139f1c663e8ec4a",
            "tokenAddress": "0xE4917899728432952F4dbcE1C526700312fE239e",
            "redirectUrl": "http://localhost:3000/token/0xE4917899728432952F4dbcE1C526700312fE239e",
            "tokenDetails": {
                "name": "ToMJ",
                "symbol": "TJ",
                "description": (
                    "ToMJ is a token that combines the timeless magic of cartoon classics with the excitement of decentralized "
                    "finance. Its vision is to bring together nostalgic fans and forward-thinking investors to build a "
                    "community-driven ecosystem. The token will be used to govern and incentivize contributions to the platform."
                ),
                "imageUrl": "https://gateway.pinata.cloud/ipfs/bafybeickti2g27cgv2kulpa37x5sakldw1rk6x5ah6szoq3ja5pmnpdd",
                "metadataURI": "https://gateway.pinata.cloud/ipfs/bafkreibuytmrvk5qw75jk3d42b2qnyyywp2adc7y3fehicwbf2lnaq4feu"
            }
        }
        agent.logger.info("\n✅ Deploy token successfully!")

        # Generate natural language reponse given the json data
        llm_message = agent.prompt_llm(prompt="Generate a message discord given the response",
                                       system_prompt=json.dumps(response))
        agent.logger.info(f"\n📝 Generated response: {llm_message}")
        responses.append({
            "message_id": message.get("id"),
            "channel_id": message.get('channel_id'),
            "response": llm_message
        })

    # json response -> reply to tweet
    for response in responses:
        message_id = response['message_id']
        channel_id = response['channel_id']
        reply_text = response['response']

        agent.connection_manager.perform_action(
            connection_name="discord",
            action_name="reply-to-message",
            params=[channel_id, message_id, reply_text]
        )
        agent.logger.info(f"\n🚀 Posting reply: '{reply_text}'")
    return
