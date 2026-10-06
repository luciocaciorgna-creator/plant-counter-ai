import streamlit as st
import cv2
import numpy as np
import pandas as pd

st.set_page_config(
    page_title="Plant Counter AI",
    layout="wide"
)

st.title("🌱 Plant Counter AI")
st.subheader("Conteo automático de plantas")

distancia_surco_cm = st.number_input(
    "Distancia entre surcos (cm)",
    min_value=10.0,
    value=52.0,
    step=1.0
)

uploaded_file = st.file_uploader(
    "Subí una foto",
    type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:

    file_bytes = np.asarray(
        bytearray(uploaded_file.read()),
        dtype=np.uint8
    )

    image = cv2.imdecode(
        file_bytes,
        cv2.IMREAD_COLOR
    )

    original = image.copy()

    hsv = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2HSV
    )

    lower_green = np.array([30, 40, 40])
    upper_green = np.array([95, 255, 255])

    mask = cv2.inRange(
        hsv,
        lower_green,
        upper_green
    )

    kernel = np.ones((5, 5), np.uint8)

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel
    )

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    plants = []
    detection_id = 1

    for c in contours:

        area = cv2.contourArea(c)

        if area < 120:
            continue

        x, y, w, h = cv2.boundingRect(c)

        centro_x = x + (w / 2)
        centro_y = y + (h / 2)

        cv2.rectangle(
            image,
            (x, y),
            (x + w, y + h),
            (0, 0, 255),
            2
        )

        cv2.putText(
            image,
            str(detection_id),
            (x, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 0),
            2
        )

        plants.append({
            "id": detection_id,
            "x": x,
            "y": y,
            "cx": centro_x,
            "cy": centro_y,
            "w": w,
            "h": h,
            "area": round(area, 2)
        })

        detection_id += 1

    col1, col2 = st.columns(2)

    with col1:

        st.subheader("Imagen Original")

        st.image(
            cv2.cvtColor(
                original,
                cv2.COLOR_BGR2RGB
            ),
            use_container_width=True
        )

    with col2:

        st.subheader("Imagen Procesada")

        st.info(
            "Los números amarillos coinciden con el ID de la tabla."
        )

        st.image(
            cv2.cvtColor(
                image,
                cv2.COLOR_BGR2RGB
            ),
            use_container_width=True
        )

    st.metric(
        "🌱 Plantas detectadas por IA",
        len(plants)
    )

    df = pd.DataFrame(plants)

    if not df.empty:

        st.subheader("Corrección de detecciones")

        df["usar"] = True

        edited_df = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True
        )

        plantas_validas = edited_df[
            edited_df["usar"] == True
        ].copy()

        st.metric(
            "✅ Plantas válidas",
            len(plantas_validas)
        )

        plantas_agregadas = st.number_input(
            "Agregar plantas faltantes",
            min_value=0,
            max_value=100,
            value=0
        )

        conteo_final = (
            len(plantas_validas)
            + plantas_agregadas
        )

        st.metric(
            "🌱 Conteo Final Corregido",
            conteo_final
        )

        if len(plantas_validas) >= 2:

            posiciones = sorted(
                plantas_validas["cy"].tolist()
            )

            distancias_px = []

            for i in range(
                len(posiciones) - 1
            ):
                distancias_px.append(
                    posiciones[i + 1]
                    - posiciones[i]
                )

            if len(distancias_px) > 0:

                ancho_px = image.shape[1]

                cm_por_px = (
                    distancia_surco_cm /
                    (ancho_px * 0.5)
                )

                distancias_cm = [
                    d * cm_por_px
                    for d in distancias_px
                ]

                media = np.mean(
                    distancias_cm
                )

                desvio = np.std(
                    distancias_cm
                )

                cv = (
                    desvio /
                    media
                ) * 100

                densidad = (
                    100 /
                    media
                )

                st.subheader(
                    "📊 Resultados"
                )

                c1, c2 = st.columns(2)

                with c1:

                    st.metric(
                        "Densidad",
                        f"{densidad:.2f} Plantas/M"
                    )

                    st.metric(
                        "Media",
                        f"{media:.2f} cm"
                    )

                with c2:

                    st.metric(
                        "Desvío estándar",
                        f"{desvio:.2f} cm"
                    )

                    st.metric(
                        "CV",
                        f"{cv:.2f}%"
                    )

        st.subheader(
            "Detalle de detecciones"
        )

        st.dataframe(
            plantas_validas,
            use_container_width=True
        )

    else:

        st.warning(
            "No se detectaron plantas."
        )
