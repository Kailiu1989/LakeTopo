class WallCorrugationsMaterialProperty {
    constructor(options) {
        this._definitionChanged = new Cesium.Event();
        this._color = undefined;
        this.color = options.color;
        this.duration = options.duration;
        this.trailImage = options.trailImage;
        this._time = (new Date()).getTime();
    };

    get isConstant() {
        return false;
    }

    get definitionChanged() {
        return this._definitionChanged;
    }

    getType(time) {
        return Cesium.Material.WallCorrugationsMaterialType;
    }

    getValue(time, result) {
        if (!Cesium.defined(result)) {
            result = {};
        }
        
        result.color = Cesium.Property.getValueOrDefault(this._color, time, Cesium.Color.WHITE, result.color);
        result.time = (((new Date()).getTime() - this._time) % this.duration) / this.duration;
        if (this.trailImage) {
            result.image = this.trailImage;
        } else {
            result.image = Cesium.Material.WallCorrugationsMaterialImage
        }
        return result
    }

    equals(other) {
        return (this === other ||
            (other instanceof WallCorrugationsMaterialProperty &&
                Cesium.Property.equals(this._color, other._color))
        )
    }
}

Object.defineProperties(WallCorrugationsMaterialProperty.prototype, {
    color: Cesium.createPropertyDescriptor('color'),
})



Cesium.WallCorrugationsMaterialProperty = WallCorrugationsMaterialProperty;
Cesium.Material.WallCorrugationsMaterialProperty = 'WallCorrugationsMaterialProperty';
Cesium.Material.WallCorrugationsMaterialType = 'WallCorrugationsMaterialType';
Cesium.Material.WallCorrugationsMaterialImage = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAgAAAAAgCAYAAABkS8DlAAAACXBIWXMAAAsTAAALEwEAmpwYAAAFFmlUWHRYTUw6Y29tLmFkb2JlLnhtcAAAAAAAPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgNS42LWMxNDggNzkuMTY0MDM2LCAyMDE5LzA4LzEzLTAxOjA2OjU3ICAgICAgICAiPiA8cmRmOlJERiB4bWxuczpyZGY9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkvMDIvMjItcmRmLXN5bnRheC1ucyMiPiA8cmRmOkRlc2NyaXB0aW9uIHJkZjphYm91dD0iIiB4bWxuczp4bXA9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC8iIHhtbG5zOmRjPSJodHRwOi8vcHVybC5vcmcvZGMvZWxlbWVudHMvMS4xLyIgeG1sbnM6cGhvdG9zaG9wPSJodHRwOi8vbnMuYWRvYmUuY29tL3Bob3Rvc2hvcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RFdnQ9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZUV2ZW50IyIgeG1wOkNyZWF0b3JUb29sPSJBZG9iZSBQaG90b3Nob3AgMjEuMCAoV2luZG93cykiIHhtcDpDcmVhdGVEYXRlPSIyMDIzLTA5LTEwVDIxOjQ3OjUyKzA4OjAwIiB4bXA6TW9kaWZ5RGF0ZT0iMjAyMy0wOS0xMFQyMjoyOToyNCswODowMCIgeG1wOk1ldGFkYXRhRGF0ZT0iMjAyMy0wOS0xMFQyMjoyOToyNCswODowMCIgZGM6Zm9ybWF0PSJpbWFnZS9wbmciIHBob3Rvc2hvcDpDb2xvck1vZGU9IjMiIHBob3Rvc2hvcDpJQ0NQcm9maWxlPSJzUkdCIElFQzYxOTY2LTIuMSIgeG1wTU06SW5zdGFuY2VJRD0ieG1wLmlpZDo4OGE1NmU2OC01MjZhLWIzNDMtYThiZS05OWNhMDM2YTUxMDUiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6ODhhNTZlNjgtNTI2YS1iMzQzLWE4YmUtOTljYTAzNmE1MTA1IiB4bXBNTTpPcmlnaW5hbERvY3VtZW50SUQ9InhtcC5kaWQ6ODhhNTZlNjgtNTI2YS1iMzQzLWE4YmUtOTljYTAzNmE1MTA1Ij4gPHhtcE1NOkhpc3Rvcnk+IDxyZGY6U2VxPiA8cmRmOmxpIHN0RXZ0OmFjdGlvbj0iY3JlYXRlZCIgc3RFdnQ6aW5zdGFuY2VJRD0ieG1wLmlpZDo4OGE1NmU2OC01MjZhLWIzNDMtYThiZS05OWNhMDM2YTUxMDUiIHN0RXZ0OndoZW49IjIwMjMtMDktMTBUMjE6NDc6NTIrMDg6MDAiIHN0RXZ0OnNvZnR3YXJlQWdlbnQ9IkFkb2JlIFBob3Rvc2hvcCAyMS4wIChXaW5kb3dzKSIvPiA8L3JkZjpTZXE+IDwveG1wTU06SGlzdG9yeT4gPC9yZGY6RGVzY3JpcHRpb24+IDwvcmRmOlJERj4gPC94OnhtcG1ldGE+IDw/eHBhY2tldCBlbmQ9InIiPz4qkuRzAAAA8ElEQVR4nO3WS27CQBBAwSb3PzPOJsomCmRsIEavauP5tGXJq3fZtm1mZuZ63Wbma/NtZf/b+q9z99ZHZ1fPjt6tzJz5+ejZV92d9ewZ77zjN1/17/777Jl3KzN7Zs/4PDqzerfn7BGzt9Z7537sPwYAyBEAABAkAAAgSAAAQJAAAIAgAQAAQQIAAIIEAAAECQAACBIAABAkAAAgSAAAQJAAAIAgAQAAQQIAAIIEAAAECQAACBIAABAkAAAgSAAAQJAAAIAgAQAAQQIAAIIEAAAECQAACBIAABAkAAAgSAAAQJAAAIAgAQAAQQIAAII+ATxAA0lzy5mYAAAAAElFTkSuQmCC';
Cesium.Material.WallCorrugationsMaterialSource ="czm_material czm_getMaterial(czm_materialInput materialInput)\n\
{\n\
czm_material material = czm_getDefaultMaterial(materialInput);\n\
vec2 st = materialInput.st;\n\
vec4 colorImage = texture(image, vec2(fract(st.t - time), st.t));\n\
vec4 fragColor;\n\
fragColor.rgb = color.rgb / 1.0;\n\
fragColor = czm_gammaCorrect(fragColor);\n\
material.alpha = colorImage.a * color.a;\n\
material.diffuse = color.rgb;\n\
material.emission = fragColor.rgb;\n\
return material;\n\
}"

Cesium.Material._materialCache.addMaterial(Cesium.Material.WallCorrugationsMaterialType, {
    fabric: {
        type: Cesium.Material.WallCorrugationsMaterialType,
        uniforms: {
            color: new Cesium.Color(0.0, 0.0, 0.0, 1.0),
            image: Cesium.Material.WallCorrugationsMaterialImage,
            time: 0
        },
        source: Cesium.Material.WallCorrugationsMaterialSource
    },
    translucent: function(material) {
        return true;
    }
})
