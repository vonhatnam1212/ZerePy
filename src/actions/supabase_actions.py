from src.action_handler import register_action
from src.helpers import print_h_bar


@register_action("get-tokens")
def get_tokens(agent, **kwargs):
    agent.logger.info('RETRIEVING TOKEN DATA')
    print_h_bar()

    data = agent.connection_manager.perform_action(
        connection_name="supabase",
        action_name="get-tokens",
        params=['solana']
    )
    if not data:
        agent.logger.error("Failed to retrieve token data")
        return []

    agent.logger.info("\n✅ Data retrieved successfully!")
    return data
