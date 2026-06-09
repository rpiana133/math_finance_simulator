import plotly.graph_objects as go

def plot_candlestick(ticker, hist, period_label="3 Months"):
    period_text = f" ({period_label})" if period_label else ""

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist['Open'], high=hist['High'],
        low=hist['Low'], close=hist['Close'], name=ticker,
        increasing_line_color='#10b981', decreasing_line_color='#f43f5e',
    ))

    fig.update_layout(
        title=f"{ticker}{period_text}",
        height=450, margin=dict(l=0, r=0, t=40, b=30),
        template="plotly_white",
        hovermode="x unified",
        font=dict(family="Inter, -apple-system, sans-serif", size=12, color="#1f2937"),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
    )
    fig.update_xaxes(
        title="Date", rangeslider_visible=False,
        gridcolor='rgba(128,128,128,0.1)',
        tickformat="%b %d",
    )
    fig.update_yaxes(
        title="Price", gridcolor='rgba(128,128,128,0.1)',
        tickprefix="$", side='right'
    )
    return fig
