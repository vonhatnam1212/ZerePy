import threading
from src.action_handler import register_action
from src.helpers import print_h_bar
from src.prompts import REPLY_TWEET_PROMPT
import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()

DEPLOY_TOKEN_URL = os.getenv("DEPLOY_TOKEN_URL")


@register_action("post-tweet")
def post_tweet(agent, **kwargs):
    agent.logger.info("\n📝 GENERATING NEW TWEET")
    print_h_bar()

    agent.connection_manager.perform_action(
        connection_name="twitter",
        action_name="post-tweet",
        params=[agent.answer]
    )
    agent.logger.info("\n✅ Tweet posted successfully!")
    return True


@register_action("reply-to-tweet")
def reply_to_tweet(agent, **kwargs):
    if "timeline_tweets" in agent.state and agent.state["timeline_tweets"] is not None and len(
            agent.state["timeline_tweets"]) > 0:
        tweet = agent.state["timeline_tweets"].pop(0)
        tweet_id = tweet.get('id')
        if not tweet_id:
            return

        agent.logger.info(
            f"\n💬 GENERATING REPLY to: {tweet.get('text', '')[:50]}...")

        base_prompt = REPLY_TWEET_PROMPT.format(tweet_text=tweet.get('text'))
        system_prompt = agent._construct_system_prompt()
        reply_text = agent.prompt_llm(
            prompt=base_prompt, system_prompt=system_prompt)

        if reply_text:
            agent.logger.info(f"\n🚀 Posting reply: '{reply_text}'")
            agent.connection_manager.perform_action(
                connection_name="twitter",
                action_name="reply-to-tweet",
                params=[tweet_id, reply_text]
            )
            agent.logger.info("✅ Reply posted successfully!")
            return True
    else:
        agent.logger.info("\n👀 No tweets found to reply to...")
        return False


@register_action("like-tweet")
def like_tweet(agent, **kwargs):
    if "timeline_tweets" in agent.state and agent.state["timeline_tweets"] is not None and len(
            agent.state["timeline_tweets"]) > 0:
        tweet = agent.state["timeline_tweets"].pop(0)
        tweet_id = tweet.get('id')
        if not tweet_id:
            return False

        is_own_tweet = tweet.get(
            'author_username', '').lower() == agent.username
        if is_own_tweet:
            replies = agent.connection_manager.perform_action(
                connection_name="twitter",
                action_name="get-tweet-replies",
                params=[tweet.get('author_id')]
            )
            if replies:
                agent.state["timeline_tweets"].extend(
                    replies[:agent.own_tweet_replies_count])
            return True

        agent.logger.info(f"\n👍 LIKING TWEET: {tweet.get('text', '')[:50]}...")

        agent.connection_manager.perform_action(
            connection_name="twitter",
            action_name="like-tweet",
            params=[tweet_id]
        )
        agent.logger.info("✅ Tweet liked successfully!")
        return True
    else:
        agent.logger.info("\n👀 No tweets found to like...")
    return False


@register_action("respond-to-mentions")
def respond_to_mentions(agent, **kwargs):  # REQUIRES TWITTER PREMIUM PLAN

    filter_str = f"@{agent.username} -is:retweet"
    stream_function = agent.connection_manager.perform_action(
        connection_name="twitter",
        action_name="stream-tweets",
        params=[filter_str]
    )

    def process_tweets():
        for tweet_data in stream_function:
            tweet_id = tweet_data["id"]
            tweet_text = tweet_data["text"]
            agent.logger.info(f"Received a mention: {tweet_text}")

    processing_thread = threading.Thread(target=process_tweets)
    processing_thread.daemon = True
    processing_thread.start()


@register_action("get-mentioned-tweets")
def get_mentioned_tweets(agent, **kwargs):
    agent.logger.info("\n📝 Retrieving mentioned tweets")
    print_h_bar()

    tweets = agent.connection_manager.perform_action(
        connection_name="twitter",
        action_name="get-mentioned-tweets",
        params=[]
    )

    selected_tweets = []

    for tweet in tweets:
        tweet_id = tweet.get('id')
        tweet_text = tweet.get('text')
        agent.logger.info(f"Processing tweet: {tweet.get('text')}")

        tweet_author = tweet.get('author_id')
        tweet_username = tweet.get('username')
        if agent.connection_manager.perform_action(
                connection_name="supabase",
                action_name="check-subscribed-user",
                params=[tweet_author]
        ):
            selected_tweets.append({
                "tweet_id": tweet_id,
                "text": tweet_text,
                "username": tweet_username
            })

    agent.logger.info("\n✅ Tweets retrieved successfully!")
    return selected_tweets


@register_action("deploy-token")
def deploy_token(agent, **kwargs):
    agent.logger.info("\n📝 Deploying token")
    print_h_bar()
    # url = f"{DEPLOY_TOKEN_URL}api/memecoin/create-for-user"

    # tweets = get_mentioned_tweets(agent, **kwargs)

    tweets = [
        {
            "user_id": "2566404774",
            "tweet_id": "1898768075333435659",
            "username": "RoxorLeo",
            "text": "@RoxorLeo Create a meme token about cats"
        }
    ]

    responses = []
    for tweet in tweets:
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
        llm_tweet = agent.prompt_llm(prompt="Generate a tweet given the response under 40 words", system_prompt=json.dumps(response))
        agent.logger.info(f"\n📝 Generated response: {llm_tweet}")
        responses.append({
            "tweet_id": tweet.get('tweet_id'),
            "response": llm_tweet
        })

    # json response -> reply to tweet
    for response in responses:
        tweet_id = response['tweet_id']
        reply_text = response['response']
        agent.connection_manager.perform_action(
            connection_name="twitter",
            action_name="reply-to-tweet",
            params=[tweet_id, reply_text]
        )
        agent.logger.info(f"\n🚀 Posting reply: '{reply_text}'")
    return
