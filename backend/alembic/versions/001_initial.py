"""初始数据库迁移

Revision ID: 001
Revises:
Create Date: 2024-01-01

"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建用户表
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(50), unique=True, nullable=False),
        sa.Column('username', sa.String(100), unique=True, nullable=False),
        sa.Column('email', sa.String(200), nullable=False),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_login', sa.DateTime()),
    )

    # 创建账户表
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.String(50), unique=True, nullable=False),
        sa.Column('user_id', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('broker', sa.String(50)),
        sa.Column('total_asset', sa.Float(), default=0),
        sa.Column('cash', sa.Float(), default=0),
        sa.Column('market_value', sa.Float(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime()),
    )

    # 创建持仓表
    op.create_table(
        'positions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.String(50), nullable=False),
        sa.Column('code', sa.String(10), nullable=False),
        sa.Column('name', sa.String(100)),
        sa.Column('volume', sa.Integer(), default=0),
        sa.Column('available_volume', sa.Integer(), default=0),
        sa.Column('cost_price', sa.Float(), default=0),
        sa.Column('current_price', sa.Float(), default=0),
        sa.Column('updated_at', sa.DateTime()),
    )

    # 创建信号历史表
    op.create_table(
        'signal_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('strategy', sa.String(50), nullable=False),
        sa.Column('code', sa.String(10), nullable=False),
        sa.Column('name', sa.String(100)),
        sa.Column('action', sa.String(10), nullable=False),
        sa.Column('price', sa.Float()),
        sa.Column('reason', sa.Text()),
        sa.Column('confidence', sa.Float()),
        sa.Column('executed', sa.Boolean(), default=False),
        sa.Column('ts', sa.DateTime(), nullable=False),
    )

    # 创建评分快照表
    op.create_table(
        'score_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(10), nullable=False),
        sa.Column('name', sa.String(100)),
        sa.Column('score', sa.Float()),
        sa.Column('price', sa.Float()),
        sa.Column('premium_ratio', sa.Float()),
        sa.Column('dual_low', sa.Float()),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    # 创建索引
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_positions_account', 'positions', ['account_id'])
    op.create_index('ix_positions_code', 'positions', ['code'])
    op.create_index('ix_signals_strategy', 'signal_history', ['strategy'])
    op.create_index('ix_signals_code', 'signal_history', ['code'])
    op.create_index('ix_signals_ts', 'signal_history', ['ts'])
    op.create_index('ix_scores_date', 'score_snapshots', ['snapshot_date'])
    op.create_index('ix_scores_code', 'score_snapshots', ['code'])


def downgrade() -> None:
    op.drop_index('ix_scores_code', 'score_snapshots')
    op.drop_index('ix_scores_date', 'score_snapshots')
    op.drop_index('ix_signals_ts', 'signal_history')
    op.drop_index('ix_signals_code', 'signal_history')
    op.drop_index('ix_signals_strategy', 'signal_history')
    op.drop_index('ix_positions_code', 'positions')
    op.drop_index('ix_positions_account', 'positions')
    op.drop_index('ix_users_email', 'users')
    op.drop_index('ix_users_username', 'users')

    op.drop_table('score_snapshots')
    op.drop_table('signal_history')
    op.drop_table('positions')
    op.drop_table('accounts')
    op.drop_table('users')
