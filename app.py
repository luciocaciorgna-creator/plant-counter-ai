import streamlit as st
import cv2
import numpy as np
import pandas as pd

st.set_page_config(page_title="Plant Counter AI", layout="wide")

st.title("🌱 Plant Counter AI")

distancia_surco_cm = st.number_input(
    "Distancia entre surcos (cm)",
    min_value=10.0,
    value=52.0
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

    mask = cv2.inRange(
        hsv,
        np.array([30, 40, 40]),
        np.array([95, 255, 255])
    )

    kernel = np.ones((5, 5), np.uint8)

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel
    )

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    plants = []
    idx = 1

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
            str(idx),
            (x, y - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 0),
            2
        )

        plants.append({
            "id": idx,
            "cx": cx,
            "cy": cy,
            "area": area
        })

        idx += 1

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

            centro = image.shape[1] / 2

            surco_izq = plantas_validas[
                plantas_validas["cx"] < centro
            ]

            surco_der = plantas_validas[
                plantas_validas["cx"] >= centro
            ]

            x_izq = surco_izq["cx"].mean()
            x_der = surco_der["cx"].mean()

            distancia_surcos_px = abs(
                x_der - x_izq
            )

            cm_px = (
                distancia_surco_cm /
                distancia_surcos_px
            )

            distancias_cm = []

            for surco in [surco_izq, surco_der]:

                if len(surco) < 2:
                    continue

                posiciones = sorted(
                    surco["cy"].tolist()
                )

                for i in range(
                    len(posiciones) - 1
                ):

                    distancias_cm.append(
                        (
                            posiciones[i + 1]
                            - posiciones[i]
                        ) * cm_px
                    )

            if len(distancias_cm) > 0:

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
                    * cm_px
                    / 100
                )

                densidad_m = (
                    conteo /
                    longitud_m
                )

                densidad_ha = (
                    densidad_m *
                    10000 /
                    (distancia_surco_cm / 100)
                )

                st.subheader(
                    "📊 Resultados"
                )

                c1, c2 = st.columns(2)

                with c1:

                    st.metric(
                        "Densidad",
                        f"{densidad_m:.2f} pl/m"
                    )

                    st.metric(
                        "Densidad Ha",
                        f"{densidad_ha:,.0f}"
                    )

                with c2:

                    st.metric(
                        "Media",
                        f"{media:.2f} cm"
                    )

                    st.metric(
                        "Desvío Std",
                        f"{desvio:.2f} cm"
                    )

                    st.metric(
                        "CV",
                        f"{cv:.2f}%"
                    )
