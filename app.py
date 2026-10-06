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

    for c in contours:

        area = cv2.contourArea(c)

        if area < 120:
            continue

        x, y, w, h = cv2.boundingRect(c)

        cv2.rectangle(
            image,
            (x, y),
            (x + w, y + h),
            (0, 0, 255),
            2
        )

        plants.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "area": round(area, 2)
        })

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

    st.subheader("Detecciones detectadas")

    df = pd.DataFrame(plants)

    if len(df) > 0:

        df["usar"] = True

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True
        )

        plantas_validas = edited_df[
            edited_df["usar"] == True
   
