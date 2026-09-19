from app.models import SubscriptionTiers,Models
from sqlalchemy.exc import IntegrityError
from sqlalchemy import *
from app.db import SessionLocal
import asyncio

async def main():
    async with SessionLocal() as db:
        stmt = select(SubscriptionTiers.id).where(SubscriptionTiers.name == 'Basic')
        result = await db.execute(stmt)
        basic_id = result.scalar_one_or_none()
        stmt = select(SubscriptionTiers.id).where(SubscriptionTiers.name == 'Pro')
        result = await db.execute(stmt)
        pro_id = result.scalar_one_or_none()
        stmt = select(SubscriptionTiers.id).where(SubscriptionTiers.name == 'Premium')
        result = await db.execute(stmt)
        premium_id = result.scalar_one_or_none()
        # seeding premium model gpt-5.6 
        model = Models(model_id='gpt-5.6-sol',
                       provider='openai',
                       display_name='GPT-5.6 Sol',
                       min_tier_id=premium_id,
                       context_window=1050000,
                       max_token_schema='max_completion_tokens',
                       input_price_per_1M=4.000000,
                       output_price_per_1M=20.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        # seeding premium model gemini-3.1-pro
        model = Models(model_id='google/gemini-3.1-pro',
                       provider='google',
                       display_name='GEMINI-3.1 PRO',
                       min_tier_id=premium_id,
                       context_window=1048576,
                       max_token_schema='max_output_tokens',
                       input_price_per_1M=4.000000,
                       output_price_per_1M=18.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding premium model claude-sonnet-5
        model = Models(model_id='claude-opus-5',
                       provider='anthropic',
                       display_name='CLAUDE OPUS-5',
                       min_tier_id=premium_id,
                       context_window=1000000,
                       max_token_schema='max_tokens',
                       input_price_per_1M=5.000000,
                       output_price_per_1M=25.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding pro model gemini-3-flash
        model = Models(model_id='gemini-3.5-flash',
                       provider='google',
                       display_name='GEMINI-3 FLASH',
                       min_tier_id=pro_id,
                       context_window=1048576,
                       max_token_schema='max_output_tokens',
                       input_price_per_1M=1.500000,
                       output_price_per_1M=9.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)             
        # seeding pro model terra
        model = Models(model_id='gpt-5.6-terra',
                       provider='openai',
                       display_name='GPT-5.6 TERRA',
                       min_tier_id=pro_id,
                       context_window=200000 ,  
                       max_token_schema='max_completion_tokens',
                       input_price_per_1M=2.000000,
                       output_price_per_1M=12.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        # seeding pro model claude-haiku-4.5
        model = Models(model_id='claude-sonnet-5',
                       provider='anthropic',
                       display_name='CLAUDE SONNET-5',
                       min_tier_id=pro_id,
                       context_window=1000000,  
                       max_token_schema='max_tokens',
                       input_price_per_1M=1.000000,
                       output_price_per_1M=5.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding basic model gpt-luna
        model = Models(model_id='gpt-5.6-luna',
                       provider='openai',
                       display_name='GPT-5.6 LUNA',
                       min_tier_id=basic_id,
                       context_window=1_000_000,  
                       max_token_schema='max_completion_tokens',
                       input_price_per_1M=0.200000,
                       output_price_per_1M=1.200000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        # seeding basic model
        model = Models(model_id='gemini-3.5-flash-lite',
                         provider='google',
                         display_name='GEMINI 3.5 FLASH LITE',
                         min_tier_id=basic_id,
                         context_window=1_000_000,  
                         max_token_schema='max_output_tokens',
                         input_price_per_1M=0.250000,
                         output_price_per_1M=1.500000,
                        )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding basic model 
        model = Models(model_id='claude-haiku-4.5',
                       provider='anthropic',
                       display_name='CLAUDE HAIKU 4.5',
                       min_tier_id=basic_id,
                       context_window=1000000,
                       max_token_schema='max_tokens',
                       input_price_per_1M=1.000000,
                       output_price_per_1M=4.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)


if __name__ == '__main__':
    asyncio.run(main())










