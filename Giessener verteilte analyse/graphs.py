import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go

THREE_GROUP_COLORS = {"COPD-exklusiv": "#37969B", "Asthma-exklusiv": "#4A89DC", "Overlap": "#E9573F"}
SUB_COLORS = {
    "COPD J44.0 (Infekt)": "#37969B",
    "COPD J44.1 (Exazerbation)": "#48CFAD",
    "COPD J44.8/9 (Sonstige/Unspez.)": "#A0D468",
    "Asthma-exklusiv": "#4A89DC",
    "Overlap": "#E9573F"
}

def generate_boxplot_3groups(df_dedup_3, output_dir, date_str, today_str, p_val_3g, unit_eos):
    """
    Generates the interactive Plotly HTML boxplot for the 3 main groups.
    """
    try:
        plot_df = df_dedup_3[(df_dedup_3['Three_Group_Category'] != 'Andere') & (df_dedup_3['max_eo'].notna())].copy()
        p_str = "NA"
        if p_val_3g is not None:
            p_str = "< 0.001" if p_val_3g < 0.001 else f"= {p_val_3g:.3f}"
            
        fig1 = go.Figure()
        for g in ["COPD-exklusiv", "Asthma-exklusiv", "Overlap"]:
            g_data = plot_df[plot_df['Three_Group_Category'] == g]['max_eo']
            fig1.add_trace(go.Box(
                y=g_data,
                name=g,
                marker_color=THREE_GROUP_COLORS[g],
                showlegend=False
            ))
        fig1.update_layout(
            title={
                'text': f"Eosinophile (log-Skala)<br><sup>p-Wert (Kruskal-Wallis): {p_str} | Stand: {today_str}</sup>",
                'y': 0.95, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'size': 20}
            },
            xaxis={'title': "", 'tickfont': {'size': 16}},
            yaxis={'title': f"Eos [{unit_eos}]", 'type': "log", 'dtick': 1, 'tickfont': {'size': 16}},
            margin={'t': 150, 'b': 50, 'l': 50, 'r': 50}
        )
        fig1.write_html(os.path.join(output_dir, f"auswertung_1fhir_boxplot_eos_log_faelle_{date_str}.html"), include_plotlyjs="cdn")
    except Exception as e:
        print(f"Error creating Boxplot of 3 groups: {e}")

def generate_boxplot_subcategories(df_dedup_3, output_dir, date_str, today_str, p_val_sub, subcats, unit_eos):
    """
    Generates the interactive Plotly HTML boxplot for subcategories.
    """
    try:
        plot_df_sub = df_dedup_3[(df_dedup_3['Subcategory'].isin(subcats)) & (df_dedup_3['max_eo'].notna())].copy()
        p_sub_str = "NA"
        if p_val_sub is not None:
            p_sub_str = "< 0.001" if p_val_sub < 0.001 else f"= {p_val_sub:.3f}"
            
        fig2 = go.Figure()
        for sc in subcats:
            sc_data = plot_df_sub[plot_df_sub['Subcategory'] == sc]['max_eo']
            fig2.add_trace(go.Box(
                y=sc_data,
                name=sc,
                marker_color=SUB_COLORS[sc],
                showlegend=False
            ))
        fig2.update_layout(
            title={
                'text': f"Eosinophile (log-Skala) nach Subkategorie (Fall-Ebene)<br><sup>p-Wert (Kruskal-Wallis): {p_sub_str} | Stand: {today_str}</sup>",
                'y': 0.95, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'size': 20}
            },
            xaxis={'title': "", 'tickangle': -15, 'tickfont': {'size': 18}},
            yaxis={'title': f"Eos [{unit_eos}]", 'type': "log", 'dtick': 1, 'tickfont': {'size': 16}},
            margin={'t': 160, 'b': 160, 'l': 140, 'r': 50}
        )
        fig2.write_html(os.path.join(output_dir, f"auswertung_1fhir_boxplot_eos_log_subkategorie_faelle_{date_str}.html"), include_plotlyjs="cdn")
    except Exception as e:
        print(f"Error creating Boxplot of subcategories: {e}")

def generate_sunburst_chart(df_dedup_3, output_dir, date_str, today_str, subcats):
    """
    Generates the nested sunburst chart of Eos status.
    """
    try:
        df_sun_1 = df_dedup_3.copy()
        df_sun_1['Eos_Category'] = df_sun_1['max_eo'].apply(lambda x: "Ohne Messung" if pd.isna(x) else ("Normal (<=0.3)" if x <= 0.3 else "Erhöht (>0.3)"))
        df_sun_1_filtered = df_sun_1[~df_sun_1['Subcategory'].isin(['COPD Sonstige', 'Andere'])]
        total_valid_n = len(df_sun_1_filtered)
        
        ids_list = ["Root"]
        labels_list = [f"Gesamt-Fälle<br>n = {total_valid_n}"]
        parents_list = [""]
        values_list = [total_valid_n]
        colors_list = ["#4A89DC"]
        
        for sc in subcats:
            sc_n = len(df_sun_1_filtered[df_sun_1_filtered['Subcategory'] == sc])
            if sc_n > 0:
                ids_list.append(sc)
                labels_list.append(f"{sc}<br>n = {sc_n}")
                parents_list.append("Root")
                values_list.append(sc_n)
                colors_list.append(SUB_COLORS[sc])
                
        for sc in subcats:
            df_sc = df_sun_1_filtered[df_sun_1_filtered['Subcategory'] == sc]
            sc_total = len(df_sc)
            if sc_total == 0:
                continue
            for ec in ["Ohne Messung", "Normal (<=0.3)", "Erhöht (>0.3)"]:
                ec_n = len(df_sc[df_sc['Eos_Category'] == ec])
                pct = (ec_n / sc_total * 100) if sc_total > 0 else 0
                if ec_n > 0:
                    ids_list.append(f"{sc}_{ec}")
                    labels_list.append(f"{ec}<br>n = {ec_n} ({pct:.1f}%)")
                    parents_list.append(sc)
                    values_list.append(ec_n)
                    if ec == "Ohne Messung":
                        colors_list.append("#D3D3D3")
                    elif "Normal" in ec:
                        colors_list.append("#8CC152")
                    else:
                        colors_list.append("#DA4453")
                        
        fig_sun = go.Figure(go.Sunburst(
            ids=ids_list,
            labels=labels_list,
            parents=parents_list,
            values=values_list,
            branchvalues="total",
            marker=dict(colors=colors_list),
            textfont=dict(size=20)
        ))
        fig_sun.update_layout(
            title={'text': f"Eosinophilen-Status nach Erkrankungsuntergruppe (Fall-Ebene)<br><sup>Stand: {today_str}</sup>", 'y': 0.95, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'size': 20}},
            margin=dict(t=150, b=50, l=50, r=50)
        )
        fig_sun.write_html(os.path.join(output_dir, f"auswertung_1fhir_eos_sunburst_subkategorie_combined_faelle_{date_str}.html"), include_plotlyjs="cdn")
    except Exception as e:
        print(f"Error creating Sunburst chart: {e}")

def generate_bestimmungsrate_chart(df_leitlinie_rate, output_dir, date_str, today_str, subcats):
    """
    Generates the timeline trend line chart for Eos determination rate.
    """
    try:
        fig_line = go.Figure()
        for sc in subcats:
            df_sub = df_leitlinie_rate[df_leitlinie_rate['Subcategory'] == sc].sort_values('Year_int')
            if df_sub.empty:
                continue
            text_vals = [f"{int(m)}/{int(t)}" for m, t in zip(df_sub['Measured_Cases'], df_sub['Total_Cases'])]
            hover_vals = [f"Jahr: {y}<br>Subkategorie: {sc}<br>Quote: {r:.1f}%<br>(n = {int(m)} von {int(t)})" 
                          for y, r, m, t in zip(df_sub['Year_int'], df_sub['Rate_Percent'], df_sub['Measured_Cases'], df_sub['Total_Cases'])]
            fig_line.add_trace(go.Scatter(
                x=df_sub['Year_int'], y=df_sub['Rate_Percent'], name=sc, mode='lines+markers',
                marker=dict(size=12, color=SUB_COLORS[sc]), line=dict(width=4, color=SUB_COLORS[sc]),
                hoverinfo='text', hovertext=hover_vals
            ))
        fig_line.update_layout(
            title={'text': f"Eosinophilen-Bestimmungsquote im zeitlichen Verlauf<br><sup>Fall-Ebene | Zeitfenster [-1 Tag, +3 Tage] | Stand: {today_str}</sup>", 'y': 0.95, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'size': 20}},
            xaxis=dict(title="Jahr", tickfont=dict(size=14), dtick=1),
            yaxis=dict(title="Bestimmungsquote [%]", range=[-5, 115], tickfont=dict(size=14)),
            margin=dict(t=150, b=50, l=50, r=50)
        )
        fig_line.write_html(os.path.join(output_dir, f"fhir_eos_bestimmungsrate_verlauf_Linien_{date_str}.html"), include_plotlyjs="cdn")
    except Exception as e:
        print(f"Error creating line plot for Bestimmungsrate: {e}")

def generate_durchgaengig_pie(patient_stats, output_dir, date_str, today_str, eos_threshold, unit_eos):
    """
    Generates three cohort-specific Pie charts showing the proportion of consistently elevated patients.
    """
    cohorts_to_plot = ["COPD-exklusiv", "Asthma-exklusiv", "Overlap"]
    cohort_names_clean = {"COPD-exklusiv": "copd", "Asthma-exklusiv": "asthma", "Overlap": "overlap"}
    
    for coh in cohorts_to_plot:
        try:
            df_coh = patient_stats[patient_stats['Cohort'] == coh]
            if df_coh.empty:
                continue
                
            pie_counts = df_coh['Consistently_Elevated'].value_counts()
            labels_p = list(pie_counts.index)
            values_p = list(pie_counts.values)
            colors_pie_list = ["#8CC152" if "Nicht" in l else "#DA4453" for l in labels_p]
            
            fig_pie = go.Figure(go.Pie(
                labels=labels_p, values=values_p, textinfo='label+percent+value',
                marker=dict(colors=colors_pie_list), textfont=dict(size=20)
            ))
            fig_pie.update_layout(
                title={'text': f"Anteil der Patienten mit durchgängig erhöhten Eosinophilen (>{eos_threshold})<br><sup>{coh} | Bedingung: In >=90% aller Eos-Messungen > {eos_threshold} {unit_eos} | Stand: {today_str}</sup>", 'y': 0.95, 'x': 0.5, 'xanchor': 'center', 'yanchor': 'top', 'font': {'size': 20}},
                margin=dict(t=150, b=50, l=50, r=50)
            )
            fig_name = f"fhir_eos_durchgaengig_erhoeht_anteil_{cohort_names_clean[coh]}_{date_str}.html"
            fig_pie.write_html(os.path.join(output_dir, fig_name), include_plotlyjs="cdn")
        except Exception as e:
            print(f"Error creating Pie chart for {coh}: {e}")
