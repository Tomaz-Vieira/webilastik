import { ensureJsonArray, ensureJsonNumberTripplet, ensureOptional, toJsonValue } from '../../util/serialization';
import { Applet } from '../../client/applets/applet';
import { ensureJsonNumber, ensureJsonObject, ensureJsonString, JsonValue } from '../../util/serialization';
import { createElement, createInputParagraph } from '../../util/misc';
import { CollapsableWidget } from './collapsable_applet_gui';
import { Session } from '../../client/ilastik';
import { DataSourcePicker } from './datasource_picker';
import { CssClasses } from '../css_classes';
import { Path } from '../../util/parsed_url';
import { Encoding, ensureEncoding, encodings as precomputed_encodings } from '../../util/precomputed_chunks';
import { SelectorWidget } from './selector_widget';





export class Job{
    public readonly name: string
    public readonly uuid: string
    public readonly num_args?: number
    public readonly num_completed_steps: number
    public readonly status: string

    public constructor(params: {
        name: string,
        uuid: string,
        num_args?: number,
        num_completed_steps: number,
        status: string,
    }){
        this.name = params.name
        this.uuid = params.uuid
        this.num_args = params.num_args
        this.num_completed_steps = params.num_completed_steps
        this.status = params.status
    }

    public static fromJsonValue(data: JsonValue): Job{
        let data_obj = ensureJsonObject(data)
        let num_args = data_obj["num_args"]

        return new Job({
            name: ensureJsonString(data_obj["name"]),
            uuid: ensureJsonString(data_obj["uuid"]),
            num_args: num_args === undefined || num_args === null ? undefined : ensureJsonNumber(num_args),
            num_completed_steps: ensureJsonNumber(data_obj["num_completed_steps"]),
            status: ensureJsonString(data_obj["status"]),
        })
    }

    public static fromJsonArray(data: JsonValue): Array<Job>{
        let data_array = ensureJsonArray(data)
        return data_array.map(element => this.fromJsonValue(element))
    }
}

export const export_modes = ["PREDICTIONS", "SIMPLE_SEGMENTATION"] as const;
export type ExportMode = typeof export_modes[number];
export function ensureExportMode(value: string): ExportMode{
    const variant = export_modes.find(variant => variant === value)
    if(variant === undefined){
        throw Error(`Invalid encoding: ${value}`)
    }
    return variant
}


type State = {
    jobs: Array<Job>,
    error_message?: string,
    sink_bucket_name?: string
    sink_prefix?: Path
    sink_voxel_offset: [number, number, number],
    sink_encoder: Encoding,
    mode: ExportMode,
}

function stateFromJsonValue(data: JsonValue): State{
    let data_obj = ensureJsonObject(data)
    return {
        jobs: Job.fromJsonArray(ensureJsonArray(data_obj["jobs"])),
        error_message: ensureOptional(ensureJsonString, data_obj.error_message),
        sink_bucket_name: ensureOptional(ensureJsonString, data_obj["sink_bucket_name"]),
        sink_prefix: ensureOptional((v) => Path.parse(ensureJsonString(v)), data_obj["sink_prefix"]),
        sink_voxel_offset: ensureJsonNumberTripplet(data_obj["sink_voxel_offset"]),
        sink_encoder: ensureEncoding(ensureJsonString(data_obj["sink_encoder"])),
        mode: ensureExportMode(ensureJsonString(data_obj["mode"])),
    }
}

export class PredictionsExportWidget extends Applet<State>{
    public readonly element: HTMLElement;
    private job_table: HTMLTableElement;
    private readonly errorMessageContainer: HTMLParagraphElement;
    private bucketNameInput: HTMLInputElement;
    private prefixInput: HTMLInputElement;
    private encoderSelector: SelectorWidget<Encoding>;
    exportModeSelector: SelectorWidget<"PREDICTIONS" | "SIMPLE_SEGMENTATION">;

    public constructor({name, parentElement, session, help}: {
        name: string, parentElement: HTMLElement, session: Session, help: string[]
    }){
        super({
            name,
            session,
            deserializer: stateFromJsonValue,
            onNewState: (new_state) => this.onNewState(new_state)
        })
        this.element = new CollapsableWidget({display_name: "Export Predictions", parentElement, help}).element
        this.element.classList.add("ItkPredictionsExportApplet")

        let fieldset = createElement({tagName: "fieldset", parentElement: this.element})
        createElement({tagName: "legend", parentElement: fieldset, innerHTML: "Data Source"})

        new DataSourcePicker({name: "export_datasource_applet", parentElement: fieldset, session})

        fieldset = createElement({tagName: "fieldset", parentElement: this.element})
        createElement({tagName: "legend", parentElement: fieldset, innerHTML: "Data Sink"})

        this.bucketNameInput = createInputParagraph({
            inputType: "text", parentElement: fieldset, label_text: "Bucket name: "
        })
        this.bucketNameInput.addEventListener("focusout", () => this.setSinkParams())

        this.prefixInput = createInputParagraph({
            inputType: "text", parentElement: fieldset, label_text: "Path: "
        })
        this.prefixInput.addEventListener("focusout", () => this.setSinkParams())

        let p = createElement({tagName: "p", parentElement: fieldset})
        createElement({tagName: "label", parentElement: p, innerHTML: "Compression: "})
        this.encoderSelector = new SelectorWidget({
            parentElement: p,
            options: precomputed_encodings.filter(e => e == "raw"), //FIXME?
            optionRenderer: (opt) => opt,
            onSelection: () => this.setSinkParams(),
        })

        p = createElement({tagName: "p", parentElement: this.element})
        createElement({tagName: "label", parentElement: p, innerHTML: "Export Source: "})
        this.exportModeSelector = new SelectorWidget({
            parentElement: p,
            options: export_modes.slice(), //FIXME?
            optionRenderer: (opt) => opt,
            onSelection: () => this.setSinkParams(),
        })

        createInputParagraph({
            inputType: "button", value: "Create Job", parentElement: this.element, onClick: () => this.doRPC("start_export_job", {})
        })

        this.errorMessageContainer = createElement({tagName: "p", parentElement: this.element})

        this.job_table = createElement({tagName: "table", parentElement: this.element, cssClasses: ["ItkPredictionsExportApplet_job_table"]});
    }

    private setSinkParams(){
        this.doRPC("set_sink_params", {
            sink_bucket_name: this.bucketNameInput.value || null,
            sink_prefix: this.prefixInput.value || null,
            sink_encoder: toJsonValue(this.encoderSelector.getSelection() || null),
            mode: toJsonValue(this.exportModeSelector.getSelection() || null),
        })
    }

    protected onNewState(new_state: State){
        this.bucketNameInput.value = new_state.sink_bucket_name || ""
        this.prefixInput.value = new_state.sink_prefix?.toString() || ""
        this.encoderSelector.setSelection({selection: new_state.sink_encoder})
        this.exportModeSelector.setSelection({selection: new_state.mode})

        this.errorMessageContainer.innerHTML = ""
        if(new_state.error_message){
            createElement({
                tagName: "span",
                parentElement: this.errorMessageContainer,
                innerHTML: new_state.error_message,
                cssClasses: [CssClasses.ErrorText]
            })
        }
        this.job_table.innerHTML = ""
        let thead = createElement({tagName: "thead", parentElement: this.job_table})
            let head_tr = createElement({tagName: "tr", parentElement: thead})
                createElement({tagName: "th", parentElement: head_tr, innerHTML: "name"})
                createElement({tagName: "th", parentElement: head_tr, innerHTML: "status"})
                createElement({tagName: "th", parentElement: head_tr, innerHTML: "progress"})

        let tbody = createElement({tagName: "tbody", parentElement: this.job_table})
        for(let job of new_state.jobs){
            let job_progress = job.num_args === undefined ? "unknwown" : Math.round(job.num_completed_steps / job.num_args * 100).toString()
            let job_tr = createElement({tagName: "tr", parentElement: tbody})
                createElement({tagName: "td", parentElement: job_tr, innerHTML: job.name})
                createElement({tagName: "td", parentElement: job_tr, innerHTML: job.status})
                createElement({tagName: "td", parentElement: job_tr, innerHTML: `${job_progress}%` })
        }
    }
}
