import { Applet } from "../client/applets/applet";
import { FeatureExtractor, Session } from "../client/ilastik";
import { IViewerDriver } from "../drivers/viewer_driver";
import { createElement, removeElement } from "../util/misc";
import { PredictingWidget } from "./widgets/predicting_widget";
import { BrushingWidget } from "./widgets/brushing_overlay/brushing_widget";
import { FeatureSelectionWidget } from "./widgets/feature_selection";
import { Viewer } from "../viewer/viewer";

export class ReferencePixelClassificationWorkflowGui{
    public readonly element: HTMLElement
    public readonly feature_selection_applet: Applet<FeatureExtractor[]>
    public readonly brushing_applet: BrushingWidget;
    public readonly live_updater: PredictingWidget;
    public readonly session: Session;
    public readonly viewer: Viewer;
    private readonly socket: WebSocket;

    public constructor({parentElement, session, viewer_driver}: {
        parentElement: HTMLElement,
        session: Session,
        viewer_driver: IViewerDriver,
    }){
        this.session = session
        this.element = createElement({tagName: "div", parentElement, cssClasses: ["ReferencePixelClassificationWorkflowGui"]})
        this.viewer = new Viewer({driver: viewer_driver, ilastik_session: session})

        this.socket = session.createSocket()
        this.socket.addEventListener("error", (ev) => {
            console.error(`Session socket has throw an error: ${ev}`)
        })

        this.feature_selection_applet = new FeatureSelectionWidget({
            name: "feature_selection_applet",
            socket: this.socket,
            parentElement: this.element,
        })
        this.brushing_applet = new BrushingWidget({
            session,
            socket: this.socket,
            parentElement: this.element,
            viewer: this.viewer,
        })
        this.live_updater = new PredictingWidget({
            session,
            socket: this.socket,
            viewer: this.viewer
        })
    }

    public destroy(){
        //FIXME: close predictions and stuff
        this.brushing_applet.destroy()
        removeElement(this.element)
    }
}
