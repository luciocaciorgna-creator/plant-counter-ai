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

if uploaded_file:

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

        cx = x + (w / 2)
        cy = y + (h / 2)

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
            "cx": cx,
            "cy": cy,
            "area": area
        })

        detection_id += 1

    col1, col2 = st.columns(2)

    with col1:

        st.subheader("Imagen original")

        st.image(
            cv2.cvtColor(
                original,
                cv2.COLOR_BGR2RGB
            ),
            use_container_width=True
        )

    with col2:

        st.subheader("Imagen procesada")

        st.image(
            cv2.cvtColor(
                image,
                cv2.COLOR_BGR2RGB
            ),
            use_container_width=True
        )

    df = pd.DataFrame(plants)

    if not df.empty:

        df["usar"] = True

        st.subheader("Corrección manual")

        edited_df = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True
        )

        plantas_validas = edited_df[
            edited_df["usar"] == True
        ].copy()

        conteo_final = len(
            plantas_validas
        )

        st.metric(
            "🌱 Conteo Final",
            conteo_final
        )

        if conteo_final >= 4:

            centro_imagen = (
                image.shape[1] / 2
            )

            surco_izq = plantas_validas[
                plantas_validas["cx"]
                < centro_imagen
            ]

            surco_der = plantas_validas[
                plantas_validas["cx"]
                >= centro_imagen
            ]

            if (
                len(surco_izq) >= 2
                and
                len(surco_der) >= 2
            ):

                x_prom_izq = (
                    surco_izq["cx"].mean()
                )

                x_prom_der = (
                    surco_der["cx"].mean()
                )

                distancia_surcos_px = abs(
                    x_prom_der -
                    x_prom_izq
                )

                distancias_cm = []

                for surco in [
                    surco_izq,
                    surco_der
                ]:

                    posiciones = sorted(
                        surco["cy"].tolist()
                    )

                    for i in range(
                        len(posiciones) - 1
                    ):

                        distancia_px = (
                            posiciones[i + 1]
                            - 
