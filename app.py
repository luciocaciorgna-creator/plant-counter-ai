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

        cx = x + w / 2
        cy = y + h / 2

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
            (x, y - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
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
        st.image(
            cv2.cvtColor(
                original,
                cv2.COLOR_BGR2RGB
            ),
            caption="Original",
            use_container_width=True
        )

    with col2:
        st.image(
            cv2.cvtColor(
                image,
                cv2.COLOR_BGR2RGB
            ),
            caption="Procesada",
            use_container_width=True
        )

    df = pd.DataFrame(plants)

    if not df.empty:

        df["usar"] = True

        st.subheader("Corrección manual")

        df = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True
        )

        plantas_validas = df[
            df["usar"] == True
        ].copy()

        conteo = len(plantas_validas)

        st.metric(
            "🌱 Plantas detectadas",
            conteo
        )

        if conteo >= 4:

            xs = sorted(
                plantas_validas["cx"].tolist()
            )

            mitad = len(xs) // 2

            centro_surco_1 = np.mean(
                xs[:mitad]
            )

            centro_surco_2 = np.mean(
                xs[mitad:]
            )

            surco_1 = plantas_validas[
                np.abs(
                    plantas_validas["cx"]
                    - centro_surco_1
                )
                <
                np.abs(
                    plantas_validas["cx"]
                    - centro_surco_2
                )
            ]

            surco_2 = plantas_validas[
                np.abs(
                    plantas_validas["cx"]
                    - centro_surco_2
                )
                <=
                np.abs(
                    plantas_validas["cx"]
                    - centro_surco_1
                )
            ]

            distancia_surcos_px = abs(
                centro_surco_2
                - centro_surco_1
            )

            distancias_cm = []

            for surco in [surco_1, surco_2]:

                if len(surco) < 2:
                    continue

                posiciones = sorted(
                    surco["cy"].tolist()
                )

                for i in range(
                    len(posiciones) - 1
                ):

                    distancia_px = (
                        posiciones[i + 1]
                        - posiciones[i]
                    )

                    distancia_cm = (
                        distancia_px
                        /
                        distancia_surcos_px
                    ) * distancia_surco_cm

                    distancias_cm.append(
                        distancia_cm
                    )

            if len(distancias_cm) > 0:

                media = np.mean(
                    distancias_cm
                )

                desvio = np.std(
                    distancias_cm
                )

                cv = (
                    desvio
                    /
                    media
                ) * 100

                longitud_px = (
                    max(
                        plantas_validas["cy"]
                    )
                    -
                    min(
                        plantas_validas["cy"]
                    )
                )

                longitud_m = (
                    longitud_px
                    /
                    distancia_surcos_px
                ) * (
                    distancia_surco_cm
                    / 100
                )

                densidad_m = (
                    conteo
                    /
                    (longitud_m * 2)
                )

                densidad_ha = (
  
