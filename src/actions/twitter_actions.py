import threading
from src.action_handler import register_action
from src.helpers import print_h_bar
from src.prompts import REPLY_TWEET_PROMPT


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
    if "timeline_tweets" in agent.state and agent.state["timeline_tweets"] is not None and len(agent.state["timeline_tweets"]) > 0:
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
    if "timeline_tweets" in agent.state and agent.state["timeline_tweets"] is not None and len(agent.state["timeline_tweets"]) > 0:
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
    )

    selected_tweets = []

    for tweet in tweets:
        tweet_id = tweet.get('id')
        tweet_text = tweet.get('text')
        tweet_author = tweet.get('author_id')
        if agent.connection_manager.perform_action(
            connection_name="supabase",
            action_name="check-subscribed-user",
            params=[tweet_author]
        ):
            selected_tweets.append({
                "tweet_id": tweet_id,
                "text": tweet_text
            })

    agent.logger.info("\n✅ Tweets retrieved successfully!")
    return selected_tweets
