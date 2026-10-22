# Third-party components

This is an experimental preview, not a complete server port. No CamScanner code or resources are included.

| Component | Version / source | License |
| --- | --- | --- |
| OpenCV Android | 4.12.0, org.opencv:opencv | Apache-2.0; bundled dependencies have their own notices |
| ONNX Runtime Android | 1.23.2, com.microsoft.onnxruntime:onnxruntime-android | MIT; third-party notices |
| AndroidX Core | 1.16.0 and transitive AndroidX artifacts | Apache-2.0 |
| Android desugaring library | 2.1.5 | See included desugar notices |
| PaddleOCR eslav_PP-OCRv5_mobile_rec | Existing project's official model, converted to ONNX | PaddleOCR Apache-2.0 |

The OCR weights are not trained or quantized by this Android prototype. Format conversion is recorded in `app/src/main/assets/model-manifest.json`. The geometry is adapted from the Blanks project. Unfilled reference PDFs are copied from the project's reference forms, not from completed pupil papers.

Original license texts are bundled under `app/src/main/assets/licenses/`. Source references:

- https://github.com/opencv/opencv/tree/4.12.0
- https://github.com/microsoft/onnxruntime/tree/v1.23.2
- https://github.com/PaddlePaddle/PaddleOCR
- https://android.googlesource.com/platform/frameworks/support/
- https://github.com/google/desugar_jdk_libs

Before public distribution, audit the final native libraries and their bundled third-party dependencies, reference-form redistribution terms, release signing, and the release variant separately. A dependency URL is not a replacement for any required license text.
