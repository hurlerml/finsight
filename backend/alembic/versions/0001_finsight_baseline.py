"""Create the initial ciphertext-first finsight schema.

Revision ID: 0001_finsight
Revises:
Create Date: 2026-09-14 11:18:31.897534

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
# revision identifiers, used by Alembic.
revision: str = '0001_finsight'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agent_conversations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_conversations_updated_at'), 'agent_conversations', ['updated_at'], unique=False)
    op.create_table('asset_price_points',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.Enum('volksbank', 'trade_republic', 'binance', 'trading_212', 'coinbase', name='accountsource', native_enum=False, length=32), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=False),
    sa.Column('exchange', sa.String(length=32), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('open', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('high', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('low', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('close', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('adjusted', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('volume', sa.Numeric(precision=28, scale=6), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'external_id', 'exchange', 'timestamp', name='uq_asset_price_source_instrument_time')
    )
    op.create_index('ix_asset_price_instrument_time', 'asset_price_points', ['source', 'external_id', 'timestamp'], unique=False)
    op.create_index(op.f('ix_asset_price_points_external_id'), 'asset_price_points', ['external_id'], unique=False)
    op.create_index(op.f('ix_asset_price_points_source'), 'asset_price_points', ['source'], unique=False)
    op.create_table('app_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=128), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('name_blind', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_index(op.f('ix_categories_name_blind'), 'categories', ['name_blind'], unique=False)
    op.create_index('ix_categories_slug', 'categories', ['slug'], unique=False)
    op.create_index('uq_categories_name_blind', 'categories', ['name_blind'], unique=True, postgresql_where=sa.text('name_blind IS NOT NULL'))
    op.create_table('connections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.Enum('volksbank', 'trade_republic', 'binance', 'trading_212', 'coinbase', name='accountsource', native_enum=False, length=32), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('secrets_encrypted', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('name_blind', sa.LargeBinary(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_connections_name_blind'), 'connections', ['name_blind'], unique=False)
    op.create_index(op.f('ix_connections_provider'), 'connections', ['provider'], unique=False)
    op.create_index(op.f('ix_connections_source'), 'connections', ['source'], unique=False)
    op.create_index('uq_connections_source_name_blind', 'connections', ['source', 'name_blind'], unique=True, postgresql_where=sa.text('name_blind IS NOT NULL'))
    op.create_table('inflation_indices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('month', sa.String(length=7), nullable=False),
    sa.Column('index_value', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('country', 'month', 'source', name='uq_inflation_country_month_source')
    )
    op.create_index(op.f('ix_inflation_indices_country'), 'inflation_indices', ['country'], unique=False)
    op.create_index(op.f('ix_inflation_indices_month'), 'inflation_indices', ['month'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_type', sa.Enum('sync', 'normalize', 'match', 'categorize', name='jobtype', native_enum=False, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending', 'running', 'done', 'failed', 'skipped', name='jobstatus', native_enum=False, length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_job_type'), 'jobs', ['job_type'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_table('tags',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('name_blind', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tags_name_blind'), 'tags', ['name_blind'], unique=False)
    op.create_index('uq_tags_name_blind', 'tags', ['name_blind'], unique=True, postgresql_where=sa.text('name_blind IS NOT NULL'))
    op.create_table('vault_meta',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('salt', sa.LargeBinary(), nullable=False),
    sa.Column('wrapped_dek', sa.LargeBinary(), nullable=False),
    sa.Column('recovery_salt', sa.LargeBinary(), nullable=True),
    sa.Column('recovery_wrapped_dek', sa.LargeBinary(), nullable=True),
    sa.Column('recovery_version', sa.Integer(), nullable=True),
    sa.Column('recovery_confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('connection_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.Enum('volksbank', 'trade_republic', 'binance', 'trading_212', 'coinbase', name='accountsource', native_enum=False, length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('external_id_blind', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], name='fk_accounts_connection_id', ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_accounts_connection_id'), 'accounts', ['connection_id'], unique=False)
    op.create_index(op.f('ix_accounts_external_id_blind'), 'accounts', ['external_id_blind'], unique=False)
    op.create_index(op.f('ix_accounts_source'), 'accounts', ['source'], unique=False)
    op.create_index('uq_accounts_source_external_blind', 'accounts', ['source', 'external_id_blind'], unique=True, postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.create_table('agent_conversation_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['agent_conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_conversation_messages_conversation_id'), 'agent_conversation_messages', ['conversation_id'], unique=False)
    op.create_table('category_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_category_rules_category_id'), 'category_rules', ['category_id'], unique=False)
    op.create_table('portfolios',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('connection_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.Enum('volksbank', 'trade_republic', 'binance', 'trading_212', 'coinbase', name='accountsource', native_enum=False, length=32), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('external_id_blind', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portfolios_connection_id'), 'portfolios', ['connection_id'], unique=False)
    op.create_index(op.f('ix_portfolios_external_id_blind'), 'portfolios', ['external_id_blind'], unique=False)
    op.create_index(op.f('ix_portfolios_source'), 'portfolios', ['source'], unique=False)
    op.create_index('uq_portfolios_source_external_blind', 'portfolios', ['source', 'external_id_blind'], unique=True, postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.create_table('account_balance_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_account_balance_account_captured', 'account_balance_snapshots', ['account_id', 'captured_at'], unique=False)
    op.create_index(op.f('ix_account_balance_snapshots_account_id'), 'account_balance_snapshots', ['account_id'], unique=False)
    op.create_table('asset_position_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_asset_position_portfolio_captured', 'asset_position_snapshots', ['portfolio_id', 'captured_at'], unique=False)
    op.create_index(op.f('ix_asset_position_snapshots_portfolio_id'), 'asset_position_snapshots', ['portfolio_id'], unique=False)
    op.create_table('asset_trades',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('external_id_blind', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_asset_trade_portfolio_time', 'asset_trades', ['portfolio_id', 'timestamp'], unique=False)
    op.create_index(op.f('ix_asset_trades_external_id_blind'), 'asset_trades', ['external_id_blind'], unique=False)
    op.create_index(op.f('ix_asset_trades_portfolio_id'), 'asset_trades', ['portfolio_id'], unique=False)
    op.create_index('uq_asset_trades_portfolio_external_blind', 'asset_trades', ['portfolio_id', 'external_id_blind'], unique=True, postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.create_table('portfolio_value_points',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('portfolio_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('history_range', sa.String(length=8), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('portfolio_id', 'history_range', 'timestamp', name='uq_portfolio_value_range_time')
    )
    op.create_index(op.f('ix_portfolio_value_points_history_range'), 'portfolio_value_points', ['history_range'], unique=False)
    op.create_index(op.f('ix_portfolio_value_points_portfolio_id'), 'portfolio_value_points', ['portfolio_id'], unique=False)
    op.create_index('ix_portfolio_value_portfolio_time', 'portfolio_value_points', ['portfolio_id', 'timestamp'], unique=False)
    op.create_table('sync_state',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('idle', 'running', 'backfilling', 'success', 'error', name='syncstatus', native_enum=False, length=32), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id')
    )
    op.create_index('ix_sync_state_account_id', 'sync_state', ['account_id'], unique=False)
    op.create_table('transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('booking_month_blind', sa.LargeBinary(), nullable=True),
    sa.Column('external_id_blind', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transactions_account_id'), 'transactions', ['account_id'], unique=False)
    op.create_index(op.f('ix_transactions_booking_month_blind'), 'transactions', ['booking_month_blind'], unique=False)
    op.create_index(op.f('ix_transactions_external_id_blind'), 'transactions', ['external_id_blind'], unique=False)
    op.create_index('uq_transactions_account_external_blind', 'transactions', ['account_id', 'external_id_blind'], unique=True, postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.create_table('transaction_embeddings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.Integer(), nullable=False),
    sa.Column('model_name', sa.String(length=160), nullable=False),
    sa.Column('dimensions', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('transaction_id', name='uq_transaction_embedding_transaction')
    )
    op.create_index(op.f('ix_transaction_embeddings_transaction_id'), 'transaction_embeddings', ['transaction_id'], unique=False)
    op.create_table('transaction_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_a_id', sa.Integer(), nullable=False),
    sa.Column('transaction_b_id', sa.Integer(), nullable=False),
    sa.Column('transfer_transaction_id', sa.Integer(), nullable=True),
    sa.Column('link_type', sa.Enum('internal_transfer', 'broker_funding', 'account_funding', name='linktype', native_enum=False, length=32), nullable=False),
    sa.Column('status', sa.Enum('confirmed', 'suggested', 'rejected', name='linkstatus', native_enum=False, length=32), server_default='confirmed', nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['transaction_a_id'], ['transactions.id'], ),
    sa.ForeignKeyConstraint(['transaction_b_id'], ['transactions.id'], ),
    sa.ForeignKeyConstraint(['transfer_transaction_id'], ['transactions.id'], name='fk_transaction_links_transfer_transaction_id', ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('transaction_a_id', 'transaction_b_id', 'link_type', name='uq_tx_link')
    )
    op.create_index('ix_transaction_links_a', 'transaction_links', ['transaction_a_id'], unique=False)
    op.create_index('ix_transaction_links_b', 'transaction_links', ['transaction_b_id'], unique=False)
    op.create_index(op.f('ix_transaction_links_status'), 'transaction_links', ['status'], unique=False)
    op.create_index(op.f('ix_transaction_links_transfer_transaction_id'), 'transaction_links', ['transfer_transaction_id'], unique=False)
    op.create_table('transaction_tags',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.Integer(), nullable=False),
    sa.Column('tag_id', sa.Integer(), nullable=False),
    sa.Column('encrypted_payload', sa.LargeBinary(), nullable=True),
    sa.Column('encryption_version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('transaction_id', 'tag_id', name='uq_transaction_tag')
    )
    op.create_index(op.f('ix_transaction_tags_tag_id'), 'transaction_tags', ['tag_id'], unique=False)
    op.create_index(op.f('ix_transaction_tags_transaction_id'), 'transaction_tags', ['transaction_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_transaction_tags_transaction_id'), table_name='transaction_tags')
    op.drop_index(op.f('ix_transaction_tags_tag_id'), table_name='transaction_tags')
    op.drop_table('transaction_tags')
    op.drop_index(op.f('ix_transaction_links_transfer_transaction_id'), table_name='transaction_links')
    op.drop_index(op.f('ix_transaction_links_status'), table_name='transaction_links')
    op.drop_index('ix_transaction_links_b', table_name='transaction_links')
    op.drop_index('ix_transaction_links_a', table_name='transaction_links')
    op.drop_table('transaction_links')
    op.drop_index(op.f('ix_transaction_embeddings_transaction_id'), table_name='transaction_embeddings')
    op.drop_table('transaction_embeddings')
    op.drop_index('uq_transactions_account_external_blind', table_name='transactions', postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.drop_index(op.f('ix_transactions_external_id_blind'), table_name='transactions')
    op.drop_index(op.f('ix_transactions_booking_month_blind'), table_name='transactions')
    op.drop_index(op.f('ix_transactions_account_id'), table_name='transactions')
    op.drop_table('transactions')
    op.drop_index('ix_sync_state_account_id', table_name='sync_state')
    op.drop_table('sync_state')
    op.drop_index('ix_portfolio_value_portfolio_time', table_name='portfolio_value_points')
    op.drop_index(op.f('ix_portfolio_value_points_portfolio_id'), table_name='portfolio_value_points')
    op.drop_index(op.f('ix_portfolio_value_points_history_range'), table_name='portfolio_value_points')
    op.drop_table('portfolio_value_points')
    op.drop_index('uq_asset_trades_portfolio_external_blind', table_name='asset_trades', postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.drop_index(op.f('ix_asset_trades_portfolio_id'), table_name='asset_trades')
    op.drop_index(op.f('ix_asset_trades_external_id_blind'), table_name='asset_trades')
    op.drop_index('ix_asset_trade_portfolio_time', table_name='asset_trades')
    op.drop_table('asset_trades')
    op.drop_index(op.f('ix_asset_position_snapshots_portfolio_id'), table_name='asset_position_snapshots')
    op.drop_index('ix_asset_position_portfolio_captured', table_name='asset_position_snapshots')
    op.drop_table('asset_position_snapshots')
    op.drop_index(op.f('ix_account_balance_snapshots_account_id'), table_name='account_balance_snapshots')
    op.drop_index('ix_account_balance_account_captured', table_name='account_balance_snapshots')
    op.drop_table('account_balance_snapshots')
    op.drop_index('uq_portfolios_source_external_blind', table_name='portfolios', postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.drop_index(op.f('ix_portfolios_source'), table_name='portfolios')
    op.drop_index(op.f('ix_portfolios_external_id_blind'), table_name='portfolios')
    op.drop_index(op.f('ix_portfolios_connection_id'), table_name='portfolios')
    op.drop_table('portfolios')
    op.drop_index(op.f('ix_category_rules_category_id'), table_name='category_rules')
    op.drop_table('category_rules')
    op.drop_index(op.f('ix_agent_conversation_messages_conversation_id'), table_name='agent_conversation_messages')
    op.drop_table('agent_conversation_messages')
    op.drop_index('uq_accounts_source_external_blind', table_name='accounts', postgresql_where=sa.text('external_id_blind IS NOT NULL'))
    op.drop_index(op.f('ix_accounts_source'), table_name='accounts')
    op.drop_index(op.f('ix_accounts_external_id_blind'), table_name='accounts')
    op.drop_index(op.f('ix_accounts_connection_id'), table_name='accounts')
    op.drop_table('accounts')
    op.drop_table('vault_meta')
    op.drop_index('uq_tags_name_blind', table_name='tags', postgresql_where=sa.text('name_blind IS NOT NULL'))
    op.drop_index(op.f('ix_tags_name_blind'), table_name='tags')
    op.drop_table('tags')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_job_type'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_inflation_indices_month'), table_name='inflation_indices')
    op.drop_index(op.f('ix_inflation_indices_country'), table_name='inflation_indices')
    op.drop_table('inflation_indices')
    op.drop_index('uq_connections_source_name_blind', table_name='connections', postgresql_where=sa.text('name_blind IS NOT NULL'))
    op.drop_index(op.f('ix_connections_source'), table_name='connections')
    op.drop_index(op.f('ix_connections_provider'), table_name='connections')
    op.drop_index(op.f('ix_connections_name_blind'), table_name='connections')
    op.drop_table('connections')
    op.drop_index('uq_categories_name_blind', table_name='categories', postgresql_where=sa.text('name_blind IS NOT NULL'))
    op.drop_index('ix_categories_slug', table_name='categories')
    op.drop_index(op.f('ix_categories_name_blind'), table_name='categories')
    op.drop_table('categories')
    op.drop_table('app_settings')
    op.drop_index(op.f('ix_asset_price_points_source'), table_name='asset_price_points')
    op.drop_index(op.f('ix_asset_price_points_external_id'), table_name='asset_price_points')
    op.drop_index('ix_asset_price_instrument_time', table_name='asset_price_points')
    op.drop_table('asset_price_points')
    op.drop_index(op.f('ix_agent_conversations_updated_at'), table_name='agent_conversations')
    op.drop_table('agent_conversations')
