import streamlit as st
import pandas as pd
import time
from core.analytics import OzonSmartAgent

st.set_page_config(page_title="Ozon Smart Autonomous Agent", layout="wide")

st.title("Ozon Smart Management & Autopilot Agent")
st.markdown("---")

if "agent" not in st.session_state:
    st.session_state.agent = OzonSmartAgent()

agent = st.session_state.agent

competitor_prices = agent.simulate_osint_competitors()
df_analytics = agent.calculate_unit_economics(competitor_prices)
advice_list = agent.generate_executive_advice(df_analytics)

col1, col2, col3 = st.columns(3)
with col1:
    total_products = len(df_analytics)
    st.metric("Total Managed SKU", total_products)
with col2:
    total_profit = df_analytics["Net Profit"].sum()
    st.metric("Estimated Run-Rate Net Profit", f"{total_profit:,.2f} RUB")
with col3:
    critical_stocks = len(df_analytics[df_analytics["Stock Left"] <= 5])
    st.metric("Critical Low Stocks (Action Required)", critical_stocks)

st.markdown("---")

st.subheader("AI Executive Director: Strategic Directives")
for advice in advice_list:
    if "CRITICAL" in advice or "GUARD" in advice:
        st.error(advice)
    elif "NOTICE" in advice:
        st.warning(advice)
    else:
        st.info(advice)

st.markdown("---")

st.subheader("Real-Time Unit Economics & Dynamic Repricing (OSINT)")
st.dataframe(df_analytics, use_container_width=True, hide_index=True)

st.markdown("---")

st.subheader("AI Content Generation & SEO Copywriting Factory")
selected_sku = st.selectbox("Select Target SKU for Instant SEO Optimization:", df_analytics["SKU"].tolist())

if selected_sku:
    seo_data = agent.generate_ai_seo_content(selected_sku)
    
    st.markdown(f"**Generated Product Card Description for {selected_sku}:**")
    st.markdown(f"> {seo_data['description']}")
    
    st.markdown("**Automated Rich SEO Keywords & Search Tags:**")
    st.code(seo_data["keywords"], language="text")

time.sleep(2)
st.rerun()