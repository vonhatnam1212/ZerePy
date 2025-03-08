import logging
from typing import Any, Dict, List
from src.connections.base_connection import BaseConnection, Action, ActionParameter
import os
from dotenv import load_dotenv, set_key
from supabase import create_client, Client


logger = logging.getLogger("connections.supabase_connection")


class SupabaseConnectionError(Exception):
    """Base exception for Supabase connection errors"""
    pass


class SupabaseConfigurationError(SupabaseConnectionError):
    """Raised when there are configuration/credential issues"""
    pass


class SupabaseAPIError(SupabaseConnectionError):
    """Raised when there are Supabase client API issues"""
    pass


class SupabaseConnection(BaseConnection):
    def __init__(self, config: Dict[str, Any]):
        logger.info("Initializing Supabase connection...")
        super().__init__(config)
        self._client = None

    @property
    def is_llm_provider(self):
        return False

    def validate_config(self, config) -> Dict[str, Any]:
        """
        Validate config from JSON

        Args:
            config: dictionary containing all the config values for that connection

        Returns:
            Dict[str, Any]: Returns the config if valid

        Raises:
            Error if the configuration is not valid
        """
        return config

    def configure(self, **kwargs) -> bool:
        """
        Configure the connection with necessary credentials.

        Args:
            **kwargs: Configuration parameters

        Returns:
            bool: True if configuration was successful, False otherwise
        """
        """Sets up Supabase connection"""
        logger.info("\n🤖 SUPABASE CLIENT SETUP")

        if self.is_configured():
            logger.info("Supabase Client is already configured.")
            response = input("Do you want to reconfigure? (y/n): ")
            if response.lower() != 'y':
                return True

        logger.info("\n📝 To get your Supabase credentials:")
        logger.info("1. Go to your project dashboard")
        logger.info("2. In your project settings, navigate to API Settings")
        logger.info("3. SUPABASE_URL should be your Project URL")
        logger.info(
            "4. SUPABASE_KEY should be your Project API Key and it should be `secret`")

        credentials = {
            'SUPABASE_URL':
            input("Enter your SUPABASE URL (url): "),
            'SUPABASE_KEY':
            input("Enter your SUPABASE KEY (key): ")
        }

        try:
            if not os.path.exists('.env'):
                with open('.env', 'w') as f:
                    f.write('')

            for key, value in credentials.items():
                set_key('.env', key, value)
                logger.debug(f"Saved {key} to .env")

            logger.info("\n✅ Supbase configuration successfully saved!")
            logger.info("Your credentials has been stored in the .env file.")
            return True

        except Exception as e:
            logger.error(f"Configuration failed: {e}")
            return False

    def is_configured(self, verbose=False) -> bool:
        """
        Check if the connection is properly configured and ready for use.

        Returns:
            bool: True if the connection is configured, False otherwise
        """
        try:
            self._get_credentials()
            logger.debug("Supabase configuration is valid")
            return True

        except Exception as e:
            if verbose:
                error_msg = str(e)
                if isinstance(e, SupabaseConfigurationError):
                    error_msg = f"Configuration error: {error_msg}"
                logger.error(f"Configuration validation failed: {error_msg}")
            return False

    def register_actions(self):
        """
        Register all available actions for this connection.
        Should populate self.actions with action_name -> handler mappings.
        """
        self.actions = {
            "get-tokens": Action(
                name="get-tokens",
                parameters=[
                    ActionParameter("chain", True, str,
                                    "The input chain name"),
                ],
                description="Get top 10 tokens from the given chain"
            ),
            "get-token-trades": Action(
                name="get-token-trades",
                parameters=[
                    ActionParameter("mint_address", True, str,
                                    "The input mint address of the token"),
                ],
                description="List all trades for a specific token"
            ),
            "check-subscribed-user": Action(
                name="check-subscribed-user",
                parameters=[
                    ActionParameter("user_id", True, str,
                                    "User id to check if subscribed"),
                ],
                description="Returns True if user is subscribed"
            )
        }

    def perform_action(self, action_name: str, kwargs) -> Any:
        if action_name not in self.actions:
            raise KeyError(f"Unknown action: {action_name}")

        action = self.actions[action_name]
        errors = action.validate_params(kwargs)
        logger.info(kwargs)
        if errors:
            raise ValueError(f"Invalid parameters: {', '.join(errors)}")

        # Call the appropriate method based on action name
        method_name = action_name.replace('-', '_')
        method = getattr(self, method_name)
        return method(**kwargs)

    def _get_credentials(self) -> Dict[str, str]:
        """Get Supabase credentials from environment with validation"""
        logger.debug("Retrieving Twitter credentials")
        load_dotenv()

        required_vars = {
            'SUPABASE_URL': 'client url',
            'SUPABASE_KEY': 'client key',
        }

        credentials = {}
        missing = []

        for env_var, description in required_vars.items():
            value = os.getenv(env_var)
            if not value:
                missing.append(description)
            credentials[env_var] = value

        if missing:
            error_msg = f"Missing Supabase credentials: {', '.join(missing)}"
            raise SupabaseConfigurationError(error_msg)

        logger.debug("All required credentials found")
        return credentials

    def _get_client(self) -> Client:
        """Get or create Supabase client"""
        if not self._client:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            if not url and not key:
                raise SupabaseConfigurationError(
                    "Supabase url and/or key not found in environment")
            self._client = create_client(url, key)
        return self._client

    def get_tokens(self, chain: str, **kwargs) -> List:
        """Generate top 10 tokens"""
        try:
            client = self._get_client()
            response = client.table("chains").select(
                "id").eq("name", chain).execute()
            logger.info(response.data)
            chain_id = response.data[0]['id']

            response = client.table('tokens').select(
                '*').eq('chain_id', chain_id).order("price", desc=True).limit(10).execute()
            return response.data
        except Exception as e:
            raise SupabaseAPIError(f"Query failed: {e}")

    def check_subscribed_user(self, user_id: str) -> bool:
        """Get user mentions"""
        try:
            client = self._get_client()

            response = client.table('x_users') \
                .select('account_id') \
                .eq('account_id', user_id) \
                .eq('is_active', True) \
                .execute()

            return len(response.data) > 0
        except Exception as e:
            raise SupabaseAPIError(f"Query failed: {e}")
