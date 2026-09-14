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
        # seeding premium model gpt-5.6 terra
        model = Models(model_id='openai/gpt-5.6-terra',
                       provider='openai',
                       display_name='GPT-5.6 TERRA',
                       min_tier_id=premium_id,
                       context_window=1050000,
                       input_price_per_1M=2.500000,
                       output_price_per_1M=15.000000,
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
                       input_price_per_1M=2.000000,
                       output_price_per_1M=12.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding premium model claude-sonnet-5
        model = Models(model_id='anthropic/claude-sonnet-5',
                       provider='anthropic',
                       display_name='CLAUDE SONNET-5',
                       min_tier_id=premium_id,
                       context_window=1000000,
                       input_price_per_1M=2.000000,
                       output_price_per_1M=10.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding pro model gemini-3-flash
        model = Models(model_id='google/gemini-3-flash',
                       provider='google',
                       display_name='GEMINI-3 FLASH',
                       min_tier_id=pro_id,
                       context_window=1048576,
                       input_price_per_1M=0.500000,
                       output_price_per_1M=3.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)             
        # seeding pro model o4-mini
        model = Models(model_id='openai/o4-mini',
                       provider='openai',
                       display_name='O4-MINI',
                       min_tier_id=pro_id,
                       context_window=200000 ,  
                       input_price_per_1M=1.000000,
                       output_price_per_1M=4.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        # seeding pro model claude-haiku-4.5
        model = Models(model_id='anthropic/claude-4.5-haiku',
                       provider='anthropic',
                       display_name='CLAUDE HAIKU-4.5',
                       min_tier_id=pro_id,
                       context_window=200000,  
                       input_price_per_1M=1.000000,
                       output_price_per_1M=5.000000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding basic model qwen3 Instruct
        model = Models(model_id='qwen/qwen3-235b-a22b-instruct-2507',
                       provider='qwen',
                       display_name='Qwen-3 235b',
                       min_tier_id=basic_id,
                       context_window=262144,  
                       input_price_per_1M=0.264000,
                       output_price_per_1M=1.060000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        # seeding basic model deepseek v3
        model = Models(model_id='deepseek-ai/deepseek-v3',
                         provider='deepseekai',
                         display_name='DEEPSEEK V3',
                         min_tier_id=basic_id,
                         context_window=128000,  
                         input_price_per_1M=1.450000,
                         output_price_per_1M=1.450000,
                        )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)
        #seeding basic model Meta llama 4
        model = Models(model_id='meta/llama-4-maverick-instruct',
                       provider='meta',
                       display_name='LLAMA-4 MAVERICK',
                       min_tier_id=basic_id,
                       context_window=1000000,  
                       input_price_per_1M=0.250000,
                       output_price_per_1M=0.950000,
                      )
        db.add(model)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        await db.refresh(model)


if __name__ == '__main__':
    asyncio.run(main())










