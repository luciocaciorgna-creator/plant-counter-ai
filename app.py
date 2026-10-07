import streamlit as st
import cv2
import numpy as np
import pandas as pd

st.set_page_config(
    page_title="Plant Counter AI V0.8",
    layout="wide"
)

st.title("🌱 Plant Counter AI")
st.subheader("Stand de plantas")

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

    for c in contours:

        area = cv2.contourArea(c)

        if area < 120:
            continue

        x, y, w, h = cv2.boundingRect(c)

        cx = x + w / 2
        cy = y + h / 2

        plants.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "cx": cx,
            "cy": cy,
            "area": area
        })

    df = pd.DataFrame(plants)

    if not df.empty:

        xs = sorted(
            df["cx"].tolist()
        )

        mitad = len(xs) // 2

        centro_surco_1 = np.mean(
            xs[:mitad]
        )

        centro_surco_2 = np.mean(
            xs[mitad:]
        )

        surco_1 = df[
            np.abs(
                df["cx"]
                - centro_surco_1
            )
            <
            np.abs(
                df["cx"]
                - centro_surco_2
            )
        ]

        surco_2 = df[
            np.abs(
                df["cx"]
                - centro_surco_2
            )
            <=
            np.abs(
                df["cx"]
                - centro_surco_1
            )
        ]

        altura = image.shape[0]

        cv2.line(
            image,
            (int(centro_surco_1), 0),
            (int(centro_surco_1), altura),
            (0, 255, 255),
            3
        )

        cv2.line(
            image,
            (int(centro_surco_2), 0),
            (int(centro_surco_2), altura),
            (0, 255, 255),
            3
        )

        for idx, row in df.iterrows():

            x = int(row["x"])
            y = int(row["y"])
            w = int(row["w"])
            h = int(row["h"])

            cx = int(row["cx"])
            cy = int(row["cy"])

            cv2.rectangle(
                image,
                (x, y),
                (x + w, y + h),
                (0, 0, 255),
                2
            )

            cv2.circle(
                image,
                (cx, cy),
                5,
                (255, 0, 0),
                -1
            )

        distancia_surcos_px = abs(
            centro_surco_2
            - centro_surco_1
        )

        def estadisticas_surco(df_surco):

            if len(df_surco) < 2:
                return None

            posiciones = sorted(
                df_surco["cy"].tolist()
            )

            distancias_cm = []

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

            return {
                "plantas": len(df_surco),
                "media": media,
                "desvio": desvio,
                "cv": cv
            }

        stats_1 = estadisticas_surco(
            surco_1
        )

        stats_2 = estadisticas_surco(
            surco_2
        )

        longitud_px = (
            max(df["cy"])
            -
            min(df["cy"])
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
            len(df)
            /
            (longitud_m * 2)
        )

        densidad_ha = (
            densidad_m
            *
            10000
            /
            (
                distancia_surco_cm
                / 100
            )
        )

        medias = []

        desvios = []

        cvs = []

        for s in [stats_1, stats_2]:

            if s:

                medias.append(
                    s["media"]
                )

                desvios.append(
                    s["desvio"]
                )

                cvs.append(
                    s["cv"]
                )

        media_general = np.mean(
            medias
        )

        desvio_general = np.mean(
            desvios
        )

        cv_general = np.mean(
            cvs
        )

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

        st.subheader(
            "📊 Resultados por Surco"
        )

        c1, c2 = st.columns(2)

        with c1:

            st.markdown(
                "### Surco 1"
            )

            if stats_1:

                st.metric(
                    "Plantas",
                    stats_1["plantas"]
                )

                st.metric(
                    "Media",
                    f"{stats_1['media']:.2f} cm"
                )

                st.metric(
                    "Desvío",
                    f"{stats_1['desvio']:.2f}"
                )

                st.metric(
                    "CV",
                    f"{stats_1['cv']:.2f}%"
                )

        with c2:

            st.markdown(
                "### Surco 2"
            )

            if stats_2:

                st.metric(
                    "Plantas",
                    stats_2["plantas"]
                )

                st.metric(
                    "Media",
                    f"{stats_2['media']:.2f} cm"
                )

                st.metric(
                    "Desvío",
                    f"{stats_2['desvio']:.2f}"
                )

                st.metric(
                    "CV",
                    f"{stats_2['cv']:.2f}%"
                )

        st.subheader(
            "📈 Promedio General"
        )

        c3, c4 = st.columns(2)

        with c3:

            st.metric(
                "Densidad",
                f"{densidad_m:.2f} pl/m"
            )

            st.metric(
                "Densidad Ha",
                f"{densidad_ha:,.0f}"
            )

        with c4:

            st.metric(
                "Media",
                f"{media_general:.2f} cm"
            )

            st.metric(
                "Desvío",
                f"{desvio_general:.2f}"
            )

            st.metric(
                "CV",
                f"{cv_general:.2f}%"
            )

else:

    st.info(
        "Subí una imagen para comenzar."
    )
