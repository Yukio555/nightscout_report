import requests
from datetime import datetime, timedelta
import hashlib
import pytz
import json

# Nightscout設定
NIGHTSCOUT_URL = "https://ren-cgm.azurewebsites.net"
API_SECRET = "enoq19780509yyy"
API_SECRET_HASH = hashlib.sha1(API_SECRET.encode()).hexdigest()

# 日本時間のタイムゾーン
JST = pytz.timezone('Asia/Tokyo')

def get_nightscout_data(date_str):
    """指定日のNightscoutデータを取得"""
    jst_start = JST.localize(datetime.strptime(date_str + " 00:00:00", "%Y-%m-%d %H:%M:%S"))
    jst_end = jst_start + timedelta(days=1)
    
    utc_start = jst_start.astimezone(pytz.UTC)
    utc_end = jst_end.astimezone(pytz.UTC)
    
    print(f"取得範囲（JST）: {jst_start} ～ {jst_end}")
    print(f"取得範囲（UTC）: {utc_start} ～ {utc_end}")
    
    headers = {"API-SECRET": API_SECRET_HASH}
    
    # 血糖値データ取得
    entries_url = f"{NIGHTSCOUT_URL}/api/v1/entries.json"
    params = {
        "find[dateString][$gte]": utc_start.isoformat(),
        "find[dateString][$lt]": utc_end.isoformat(),
        "count": 1000
    }
    entries_response = requests.get(entries_url, headers=headers, params=params)
    entries = entries_response.json() if entries_response.status_code == 200 else []
    
    # トリートメント取得
    treatments_url = f"{NIGHTSCOUT_URL}/api/v1/treatments.json"
    treatments_params = {
        "find[created_at][$gte]": utc_start.isoformat(),
        "find[created_at][$lt]": utc_end.isoformat(),
        "count": 1000
    }
    treatments_response = requests.get(treatments_url, headers=headers, params=treatments_params)
    treatments = treatments_response.json() if treatments_response.status_code == 200 else []
    
    return entries, treatments

def get_direction_arrow(direction):
    """トレンド方向を矢印に変換"""
    arrows = {
        'DoubleUp': '⇈', 'SingleUp': '↑', 'FortyFiveUp': '↗',
        'Flat': '→', 'FortyFiveDown': '↘', 'SingleDown': '↓',
        'DoubleDown': '⇊', 'NOT COMPUTABLE': '?', 'RATE OUT OF RANGE': '?'
    }
    return arrows.get(direction, '')

def parse_notes(notes):
    """ノート欄からデータを抽出"""
    if not notes:
        return None, None, None, [], None
    
    lines = notes.strip().split('\n')
    cir = None
    predicted_insulin = None
    insulin_type = None
    foods = []
    basal_amount = None
    
    if len(lines) > 0:
        first_line = lines[0].strip()
        
        # 基礎インスリン: "Tore 10" または "トレ 10"
        if first_line.startswith('Tore ') or first_line.startswith('トレ '):
            foods.append('基礎インスリン')
            parts = first_line.split()
            if len(parts) >= 2:
                try:
                    basal_amount = float(parts[1])
                except:
                    pass
            for i in range(1, len(lines)):
                if lines[i].strip():
                    foods.append(lines[i].strip())
            return cir, predicted_insulin, insulin_type, foods, basal_amount
        
        # ぶどう糖補食: "B"
        if first_line.upper() == 'B':
            foods.append('ぶどう糖補食')
            for i in range(1, len(lines)):
                if lines[i].strip():
                    foods.append(lines[i].strip())
            return cir, predicted_insulin, insulin_type, foods, basal_amount
        
        # インスリン種類のみ: "N" or "F"
        if first_line.upper() in ['N', 'F']:
            insulin_type = first_line.upper()
            for i in range(1, len(lines)):
                if lines[i].strip():
                    foods.append(lines[i].strip())
            return cir, predicted_insulin, insulin_type, foods, basal_amount
        
        # CIR形式: "Cir 18 2.9N" または "18 2.9N"
        test_line = first_line.replace('cir', '').replace('CIR', '').replace('Cir', '').strip()
        parts = test_line.split()
        is_cir_format = False
        
        if len(parts) >= 1:
            try:
                float(parts[0])
                is_cir_format = True
            except:
                pass
        
        if is_cir_format:
            if len(parts) >= 1:
                try:
                    cir = float(parts[0])
                except:
                    pass
            if len(parts) >= 2:
                second_part = parts[1].strip()
                if second_part and second_part[-1].upper() in ['N', 'F']:
                    insulin_type = second_part[-1].upper()
                    insulin_part = second_part[:-1]
                else:
                    insulin_part = second_part
                try:
                    predicted_insulin = float(insulin_part)
                except:
                    pass
            for i in range(1, len(lines)):
                if lines[i].strip():
                    foods.append(lines[i].strip())
        else:
            # それ以外: 全て食べ物
            for line in lines:
                if line.strip():
                    foods.append(line.strip())
    
    return cir, predicted_insulin, insulin_type, foods, basal_amount

def prepare_chart_data(entries, date_str):
    """Chart.js用のデータを準備"""
    if not entries:
        return [], []
    
    entries_sorted = sorted(entries, key=lambda x: x['dateString'])
    times = []
    bgs = []
    
    for e in entries_sorted:
        try:
            time = datetime.fromisoformat(e['dateString'].replace('Z', '+00:00'))
            time_jst = time.astimezone(JST)
            bg = e.get('sgv')
            if bg is not None:
                times.append(time_jst.strftime('%H:%M'))
                bgs.append(bg)
        except:
            continue
    
    return times, bgs

def create_html_report(date_str, entries, treatments):
    """HTMLレポートを作成"""
    filename = f"nightscout_report_{date_str}.html"
    
    # グラフ用データを準備
    chart_times, chart_bgs = prepare_chart_data(entries, date_str)
    
    # トリートメントを時系列順にソート
    treatments_sorted = sorted(treatments, key=lambda x: x.get('created_at', ''))
    
    # 統計情報の計算
    total_insulin = 0
    basal_insulin = 0
    total_carbs = 0
    bg_values_for_avg = []  # 平均血糖値計算用
    
    # 平均血糖値の計算（CGMデータから）
    for entry in entries:
        bg = entry.get('sgv')
        if bg is not None:
            bg_values_for_avg.append(bg)
    
    avg_bg = round(sum(bg_values_for_avg) / len(bg_values_for_avg)) if bg_values_for_avg else 0
    
    # テーブル行を作成
    table_rows = ""
    for treatment in treatments_sorted:
        time_utc = datetime.fromisoformat(treatment.get('created_at', '').replace('Z', '+00:00'))
        time_jst = time_utc.astimezone(JST)
        time_str = time_jst.strftime('%H:%M')
        
        # 実測値
        bg_check_value = treatment.get('glucose')
        if bg_check_value:
            table_rows += f"""
        <tr data-time="{time_str}">
            <td>{time_str}</td>
            <td>{bg_check_value} (実測)</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
        </tr>
        """
            continue
        
        # 血糖値
        bg_value = "-"
        bg_delta = ""
        bg_direction = ""
        if entries:
            try:
                closest_entry = min(entries, 
                                  key=lambda x: abs((datetime.fromisoformat(x['dateString'].replace('Z', '+00:00')).astimezone(JST) - time_jst).total_seconds()))
                bg_value = str(closest_entry.get('sgv', '-'))
                delta = closest_entry.get('delta')
                if delta is not None:
                    delta_rounded = round(delta)
                    bg_delta = f" ({'+' if delta_rounded > 0 else ''}{delta_rounded})"
                direction = closest_entry.get('direction')
                if direction:
                    bg_direction = f" {get_direction_arrow(direction)}"
            except:
                pass
        
        # ノートからデータを抽出
        notes = treatment.get('notes', '')
        cir, predicted_insulin, insulin_type, foods, basal_amount = parse_notes(notes)
        
        carbs = treatment.get('carbs', '')
        actual_insulin = treatment.get('insulin', '')
        
        # 統計の計算
        is_basal = any(food == '基礎インスリン' for food in foods)
        if is_basal and basal_amount:
            basal_insulin += basal_amount
        elif actual_insulin:
            try:
                total_insulin += float(actual_insulin)
            except:
                pass
        
        if carbs:
            try:
                total_carbs += float(carbs)
            except:
                pass
        
        # 食べ物を結合
        food_text = ", ".join(foods) if foods else "-"
        
        table_rows += f"""
        <tr data-time="{time_str}">
            <td>{time_str}</td>
            <td>{bg_value}{bg_delta}{bg_direction}</td>
            <td>{cir if cir else "-"}</td>
            <td>{f"{carbs}g" if carbs else "-"}</td>
            <td>{predicted_insulin if predicted_insulin else "-"}</td>
            <td>{actual_insulin if actual_insulin else "-"}</td>
            <td>{insulin_type if insulin_type else "-"}</td>
            <td>{food_text}</td>
        </tr>
        """
    
    # TCIR計算
    tcir = f"{total_carbs / total_insulin:.1f}" if total_insulin > 0 else "-"
    
    # HTML生成
    html_content = f"""
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nightscout日次レポート - {date_str}</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        body {{
            font-family: 'Arial', 'Helvetica', 'Meiryo', sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
        }}
        h1 {{
            position: sticky;
            top: 0;
            z-index: 101;
            text-align: center;
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding: 20px;
            margin: 0;
            background-color: white;
        }}
        .graph-section {{
            position: sticky;
            top: 60px;
            z-index: 100;
            padding: 20px;
            background-color: white;
            border-bottom: 2px solid #ddd;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .chart-wrapper {{
            height: 200px;
            margin-bottom: 10px;
        }}
        .stats-section {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 15px;
            padding: 20px;
            background-color: #f8f9fa;
        }}
        .stat-box {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .stat-label {{
            font-size: 12px;
            color: #666;
            margin-bottom: 8px;
            font-weight: bold;
        }}
        .stat-value {{
            font-size: 28px;
            color: #333;
            font-weight: bold;
        }}
        .stat-unit {{
            font-size: 16px;
            color: #888;
            margin-left: 3px;
        }}
        .table-section {{
            padding: 0 20px 20px 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        thead {{
            position: sticky;
            top: 310px;
            z-index: 50;
        }}
        th {{
            background-color: #4CAF50;
            color: white;
            padding: 12px 8px;
            text-align: left;
            font-weight: bold;
            border: 1px solid #ddd;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        td {{
            padding: 10px 8px;
            border: 1px solid #ddd;
            background-color: white;
        }}
        tr:nth-child(even) td {{
            background-color: #f9f9f9;
        }}
        tr:hover td {{
            background-color: #fffacd;
            cursor: pointer;
        }}
        .footer {{
            text-align: center;
            color: #666;
            font-size: 12px;
            padding: 20px;
        }}
        @media print {{
            body {{
                background-color: white;
            }}
            h1 {{
                position: relative;
                top: auto;
            }}
            .graph-section {{
                position: relative;
                top: auto;
                page-break-inside: avoid;
                box-shadow: none;
                padding-top: 0;
                margin-top: 0;
            }}
            thead {{
                position: relative;
                top: auto;
            }}
            .stats-section {{
                page-break-before: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Nightscout日次レポート - {date_str}</h1>
        
        <div class="graph-section">
            <div class="chart-wrapper">
                <canvas id="bgChart"></canvas>
            </div>
        </div>
        
        <div class="table-section">
            <table id="dataTable">
                <thead>
                    <tr>
                        <th>時刻</th>
                        <th>血糖値</th>
                        <th>CIR</th>
                        <th>糖質</th>
                        <th>予想</th>
                        <th>打った</th>
                        <th>種類</th>
                        <th>食べたもの</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows if table_rows else "<tr><td colspan='8' style='text-align:center;'>データがありません</td></tr>"}
                </tbody>
            </table>
        </div>
        
        <div class="stats-section">
            <div class="stat-box">
                <div class="stat-label">平均血糖値</div>
                <div class="stat-value">{avg_bg}<span class="stat-unit">mg/dL</span></div>
            </div>
            <div class="stat-box">
                <div class="stat-label">インスリン総量</div>
                <div class="stat-value">{total_insulin}<span class="stat-unit">単位</span></div>
                <div style="font-size: 11px; color: #999; margin-top: 5px;">(基礎除く)</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">基礎インスリン</div>
                <div class="stat-value">{basal_insulin}<span class="stat-unit">単位</span></div>
            </div>
            <div class="stat-box">
                <div class="stat-label">糖質総量</div>
                <div class="stat-value">{total_carbs}<span class="stat-unit">g</span></div>
            </div>
            <div class="stat-box">
                <div class="stat-label">TCIR</div>
                <div class="stat-value">{tcir}</div>
            </div>
        </div>
        
        <div class="footer">
            <p>Generated from Nightscout: {NIGHTSCOUT_URL}</p>
        </div>
    </div>
    
    <script>
        const chartData = {{
            labels: {json.dumps(chart_times)},
            values: {json.dumps(chart_bgs)}
        }};
        
        const ctx = document.getElementById('bgChart').getContext('2d');
        const bgChart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: chartData.labels,
                datasets: [{{
                    label: '血糖値',
                    data: chartData.values,
                    borderColor: '#2196F3',
                    backgroundColor: 'rgba(33, 150, 243, 0.1)',
                    borderWidth: 2,
                    tension: 0.1,
                    pointRadius: 3,
                    pointHoverRadius: 6
                }},
                {{
                    label: '目標範囲下限',
                    data: Array(chartData.labels.length).fill(70),
                    borderColor: '#4CAF50',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: false
                }},
                {{
                    label: '目標範囲上限',
                    data: Array(chartData.labels.length).fill(180),
                    borderColor: '#4CAF50',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: '-1',
                    backgroundColor: 'rgba(76, 175, 80, 0.1)'
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    title: {{
                        display: true,
                        text: '{date_str} 血糖値推移',
                        font: {{
                            size: 18,
                            weight: 'bold'
                        }}
                    }},
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        mode: 'index',
                        intersect: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: false,
                        min: 0,
                        max: 400,
                        title: {{
                            display: true,
                            text: '血糖値 (mg/dL)',
                            font: {{
                                weight: 'bold'
                            }}
                        }}
                    }},
                    x: {{
                        title: {{
                            display: true,
                            text: '時刻',
                            font: {{
                                weight: 'bold'
                            }}
                        }}
                    }}
                }}
            }}
        }});
        
        // テーブル行にマウスオーバーでグラフに赤点を表示
        const tableRows = document.querySelectorAll('#dataTable tbody tr');
        let highlightDataset = null;
        
        tableRows.forEach(row => {{
            row.addEventListener('mouseenter', function() {{
                const time = this.dataset.time;
                if (!time) return;
                
                let index = chartData.labels.indexOf(time);
                
                if (index === -1) {{
                    const targetMinutes = parseInt(time.split(':')[0]) * 60 + parseInt(time.split(':')[1]);
                    let minDiff = Infinity;
                    
                    chartData.labels.forEach((label, i) => {{
                        const labelMinutes = parseInt(label.split(':')[0]) * 60 + parseInt(label.split(':')[1]);
                        const diff = Math.abs(targetMinutes - labelMinutes);
                        if (diff < minDiff) {{
                            minDiff = diff;
                            index = i;
                        }}
                    }});
                }}
                
                if (index === -1 || !chartData.values[index]) return;
                
                if (highlightDataset) {{
                    bgChart.data.datasets.pop();
                }}
                
                const highlightData = Array(chartData.labels.length).fill(null);
                highlightData[index] = chartData.values[index];
                
                highlightDataset = {{
                    label: 'ハイライト',
                    data: highlightData,
                    borderColor: '#FF0000',
                    backgroundColor: '#FF0000',
                    pointRadius: 8,
                    pointHoverRadius: 10,
                    showLine: false
                }};
                
                bgChart.data.datasets.push(highlightDataset);
                bgChart.update('none');
            }});
            
            row.addEventListener('mouseleave', function() {{
                if (highlightDataset) {{
                    bgChart.data.datasets.pop();
                    highlightDataset = null;
                    bgChart.update('none');
                }}
            }});
        }});
    </script>
</body>
</html>
    """
    
    with open(filename, 'w', encoding='utf-8-sig') as f:
        f.write(html_content)
    
    print(f"HTMLレポートを作成しました: {filename}")
    return filename

def main():
    target_date = input("日付を入力してください (YYYY-MM-DD形式、Enterで今日): ").strip()
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"\n{target_date}のデータを取得中...")
    entries, treatments = get_nightscout_data(target_date)
    
    print(f"血糖値データ: {len(entries)}件")
    print(f"トリートメントデータ: {len(treatments)}件")
    
    if entries or treatments:
        html_file = create_html_report(target_date, entries, treatments)
        print(f"\nブラウザで開くには: {html_file}")
    else:
        print("データが見つかりませんでした。")

if __name__ == "__main__":
    main()
