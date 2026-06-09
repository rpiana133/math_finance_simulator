import plotly.graph_objects as go
from plotly.subplots import make_subplots

def plot_candlestick(ticker, hist, period_label="3 Months"):
    period_text = f" ({period_label})" if period_label else ""

    volume_colors = ['#10b981' if hist['Close'].iloc[i] >= hist['Open'].iloc[i] else '#f43f5e' for i in range(len(hist))]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.8, 0.2]
    )
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist['Open'], high=hist['High'],
        low=hist['Low'], close=hist['Close'], name=ticker,
        increasing_line_color='#10b981', decreasing_line_color='#f43f5e',
        line=dict(width=1)
    ), row=1, col=1)
    if len(hist) >= 20:
        sma20 = hist['Close'].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=hist.index, y=sma20, name='SMA 20',
            line=dict(color='#3b82f6', width=1.2, dash='dash')
        ), row=1, col=1)
    if len(hist) >= 50:
        sma50 = hist['Close'].rolling(50).mean()
        fig.add_trace(go.Scatter(
            x=hist.index, y=sma50, name='SMA 50',
            line=dict(color='#f59e0b', width=1.5)
        ), row=1, col=1)
    if len(hist) >= 20:
        vol_sma20 = hist['Volume'].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=hist.index, y=vol_sma20, name='Vol SMA 20',
            line=dict(color='#8b5cf6', width=1, dash='dot'), showlegend=False
        ), row=2, col=1)
    fig.add_trace(go.Bar(
        x=hist.index, y=hist['Volume'], name='Volume',
        marker_color=volume_colors, showlegend=False, opacity=0.8
    ), row=2, col=1)
    
    fig.update_layout(
        title=f"{ticker}{period_text}",
        height=500, margin=dict(l=0, r=0, t=35, b=0),
        template="plotly_white",
        hovermode="x unified",
        font=dict(family="Inter, -apple-system, sans-serif", size=11, color="#1f2937"),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation="h", y=1.12, x=0, xanchor="left", font=dict(size=10)),
    )
    fig.update_xaxes(
        title_text="Date", rangeslider_visible=False,
        gridcolor='rgba(128,128,128,0.1)', zerolinecolor='rgba(128,128,128,0.2)',
        tickformat="%b %d, %Y",
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1m", step="month", stepmode="backward"),
                dict(count=3, label="3m", step="month", stepmode="backward"),
                dict(count=6, label="6m", step="month", stepmode="backward"),
                dict(count=1, label="YTD", step="year", stepmode="todate"),
                dict(count=1, label="1y", step="year", stepmode="backward"),
                dict(step="all", label="Max")
            ]),
            bgcolor='rgba(128,128,128,0.1)', activecolor='rgba(128,128,128,0.3)',
        )
    )
    fig.update_yaxes(
        title_text="Price ($)", gridcolor='rgba(128,128,128,0.1)', zerolinecolor='rgba(128,128,128,0.2)',
        tickprefix="$", side='right'
    )
    fig.update_yaxes(
        title_text="Volume", gridcolor='rgba(128,128,128,0.1)', zerolinecolor='rgba(128,128,128,0.2)',
        row=2, col=1, tickformat=".2s", side='right'
    )
    return fig
